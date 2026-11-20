"""Replay the two archived market-order Bar Magnifier strategies offline."""

import hashlib
import json
import math
import re
import sys
import traceback
from collections import Counter
from decimal import Decimal
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "patched-runtime"))
import pine_compat

ENV = (
    (4721, "45-5", 10000, "0.10", "0.00075", 1),
    (5520, "60-10", 1000, "1", "0.001", 0),
)
fields = ("time", "open", "high", "low", "close", "volume")


def digest(x):
    return hashlib.sha256(x).hexdigest()


def candles(rows):
    return [dict(zip(fields, row, strict=True)) for row in rows]


def summarize_trade_ledger(orders, trades, capital, fraction, commission):
    balance = Decimal(capital)
    qty = entry = None
    audited = 0
    for order in orders:
        price = Decimal(str(order["price"]))
        amount = Decimal(str(order["qty"]))
        assert amount > 0 and price > 0
        if order["direction"] == "strategy.long":
            assert qty is None, order
            step = Decimal("0.001")
            # The pinned broker rounds its quote budget to ten significant
            # figures before reserving the opening fee and truncating the lot.
            budget = Decimal(f"{balance * fraction:.9e}")
            expected = (budget / (price * (1 + commission))) // step * step
            assert amount == expected, (order, str(expected), str(balance), str(budget))
            balance -= amount * price * (1 + commission)
            qty, entry = amount, price
            audited += 1
        else:
            assert order["direction"] in ("strategy.exit", "strategy.close"), order
            assert qty == amount and entry is not None, order
            balance += amount * price * (1 - commission)
            qty = entry = None
    for row in trades:
        size, fill1, fill2 = (
            Decimal(str(x)) for x in (row["qty"], row["entryPrice"], row["exitPrice"])
        )
        gross = size * (fill2 - fill1)
        fees = size * (fill2 + fill1) * commission
        assert math.isclose(
            row["profit"], float(gross - fees), rel_tol=0, abs_tol=1e-8
        ), row
    return audited, qty, balance


audit = json.loads((root / "market-archive-sources.json").read_bytes())
runs = []
for ident, frame, capital, fraction, fee, slippage in ENV:
    source = (root / f"source-{ident}.pine").read_bytes()
    assert digest(source) == audit[str(ident)]
    code, removed = re.subn(
        r"(?m)^/\*backtest\r?\n[\s\S]*?^\*/\r?\n", "", source.decode()
    )
    assert removed == 1
    program = pine_compat.compile_script(code)
    paths = sorted(root.glob(f"feed-*-{frame}-*.json"))
    assert len(paths) == 4
    for path in paths:
        raw = path.read_bytes()
        p = json.loads(raw)
        chart, lower = candles(p["chart"]), candles(p["intrabar"])
        ratio = p["chartMs"] // p["ltfMs"]
        assert ratio * p["ltfMs"] == p["chartMs"]
        assert [i["time"] for i in chart] == list(
            range(p["from"], p["to"], p["chartMs"])
        )
        assert [i["time"] for i in lower] == list(range(p["from"], p["to"], p["ltfMs"]))
        groups = [
            {"chartBarIndex": i, "bars": lower[i * ratio : (i + 1) * ratio]}
            for i in range(len(chart))
        ]
        scale = 10 if p["symbol"] == "BTCUSDT" else 100
        args = {
            "chart_symbol": "BINANCE:" + p["symbol"],
            "chart_timeframe": p["chartTimeframe"],
            "request_bars": {
                "$chart": {
                    "currency": "USDT",
                    "minMove": 1,
                    "priceScale": scale,
                    "quantityStep": "0.001",
                    "minContract": "0.001",
                    "pointValue": 1,
                }
            },
            "magnifier_bars": {"schemaVersion": 1, "chartBars": groups},
        }
        record = {
            "id": ident,
            "feed": path.name,
            "feed_sha256": digest(raw),
            "source_sha256": digest(source),
            "chart_count": len(chart),
            "lower_count": len(lower),
            "fee_percent": 100 * float(fee),
            "slippage_ticks": slippage,
        }
        try:
            result = program.run(chart, **args)
            assert result == pine_compat.run_script(code, chart, **args)
            report = result["strategy"]
            assert not result["diagnostics"], Counter(
                x["code"] for x in result["diagnostics"]
            )
            assert not report["diagnostics"], Counter(
                x["code"] for x in report["diagnostics"]
            )
            assert report["trades"]
            min_equity = min(x["equity"] for x in report["equity"])
            max_observed = max(x["high"] for x in chart) + slippage / scale
            minimum_order_size = (
                min_equity * float(fraction) / (max_observed * (1 + float(fee)))
            )
            assert minimum_order_size > 0.001, minimum_order_size
            record["sample_sizing_lower_bound"] = minimum_order_size
            opens, size, cash = summarize_trade_ledger(
                report["orders"],
                report["trades"],
                capital,
                Decimal(fraction),
                Decimal(fee),
            )
            assert bool(size) == bool(report["position"][-1]["size"])
            assert math.isclose(
                float(cash), report["equity"][-1]["cash"], rel_tol=0, abs_tol=1e-7
            )
            record.update(
                {
                    "trades": report["trades"],
                    "orders": report["orders"],
                    "opens": opens,
                    "closed": len(report["trades"]),
                    "end_cash_USDT": str(cash),
                    "end_position": report["position"][-1]["size"],
                    "verified_exact_pct_fills": True,
                    "magnifier_fallbacks": 0,
                }
            )
        except (ValueError, AssertionError, KeyError, TypeError):
            record["error"] = traceback.format_exc(limit=2)
        runs.append(record)
        (root / "market-replay.json").write_text(
            json.dumps(runs, indent=2) + "\n", encoding="utf-8"
        )
