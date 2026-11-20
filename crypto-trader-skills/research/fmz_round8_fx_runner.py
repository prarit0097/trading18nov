"""Isolated Pine Compat replay of the preserved FMZ #5540 source."""

import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

SOURCE_SHA = "5d34d4e559e33222ee982c13ba6a9f0fc03e8f0f8233c79eb3f206ba94047a44"
RUNTIME_SHA = "973d03e34fefa09c324cbfa3f82bfb374d7ced058f4a826d4a04fb0de0ef0b65"
FEE = 0.00075
CAPITAL = 20_000
DATE_FX = {1790812800000: 0.99935, 1793491200000: 0.99878}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bars(rows):
    fields = ("time", "open", "high", "low", "close", "volume")
    return [dict(zip(fields, row, strict=True)) for row in rows]


def guard_flat_exits(match):
    return "    if strategy.position_size != 0\n" + "".join(
        "    " + line for line in match[0].splitlines(keepends=True)
    )


def run(work):
    sys.path.insert(0, str(work))
    assert digest((work / "pine_compat/pine_compat.pyd").read_bytes()) == RUNTIME_SHA
    import pine_compat

    source = (work / "source-5540.pine").read_bytes()
    assert digest(source) == SOURCE_SHA
    code, removed = re.subn(
        r"(?m)^/\*backtest\r?\n[\s\S]*?^\*/\r?\n", "", source.decode()
    )
    assert removed == 1
    assert all(
        text in code
        for text in (
            "currency='USD'",
            "strategy.equity / close",
            "use_bar_magnifier = true",
        )
    )
    observer = (
        code + '\nplot(strategy.position_size == 0 ? 1 : 0, title="Diagnostic Flat")\n'
    )
    guarded, replaced = re.subn(
        r"(?m)(?:^    strategy\.exit\('TP[1-4]'[^\n]*\n){4}", guard_flat_exits, code
    )
    assert replaced == 1

    rate_bytes = (work / "coinbase-fx-input.json").read_bytes()
    rates = json.loads(rate_bytes)
    actual_rate = {
        row["effectiveTime"]: row["rate"] for row in rates["pairs"][0]["rates"]
    }
    assert all(actual_rate[time] == rate for time, rate in DATE_FX.items())
    program = pine_compat.compile_script(code)
    feed_paths = sorted(work.glob("feed-*-1-10S-*.json"))
    assert len(feed_paths) == 4
    results = []
    for path in feed_paths:
        raw = path.read_bytes()
        feed = json.loads(raw)
        market = feed["symbol"]
        start, end = feed["from"], feed["to"]
        assert market in ("BTCUSDT", "ETHUSDT")
        assert end == start + 86_400_000
        chart, lower = bars(feed["chart"]), bars(feed["intrabar"])
        assert [row["time"] for row in chart] == list(range(start, end, 60_000))
        assert [row["time"] for row in lower] == list(range(start, end, 10_000))
        groups = [
            {"chartBarIndex": i, "bars": lower[i * 6 : (i + 1) * 6]}
            for i in range(len(chart))
        ]
        scale = 10 if market == "BTCUSDT" else 100
        options = {
            "chart_symbol": f"BINANCE:{market}",
            "chart_timeframe": "1",
            "request_bars": {
                "$chart": {
                    "minMove": 1,
                    "priceScale": scale,
                    "pointValue": 1,
                    "quantityStep": "0.001",
                    "minContract": "0.001",
                    "currency": "USDT",
                },
                "$currencyRates": rates,
            },
            "magnifier_bars": {"schemaVersion": 1, "chartBars": groups},
        }
        result = program.run(chart, **options)
        assert result == pine_compat.run_script(code, chart, **options)
        assert not result["diagnostics"], Counter(
            d["code"] for d in result["diagnostics"]
        )
        broker = result["strategy"]
        observed = pine_compat.run_script(observer, chart, **options)
        assert observed["strategy"] == broker
        flat = sum(observed["plots"][-1]["values"])
        # The archive intentionally sends a disabled TP leg as na while flat.
        diagnostics = dict(Counter(row["code"] for row in broker["diagnostics"]))
        assert diagnostics == {"E_STRATEGY_EXIT_TICKS": flat}
        guard_broker = pine_compat.run_script(guarded, chart, **options)["strategy"]
        assert guard_broker == {**broker, "diagnostics": []}
        if not results:
            incomplete = {
                **options,
                "magnifier_bars": {"schemaVersion": 1, "chartBars": groups[:-1]},
            }
            control = program.run(chart, **incomplete)
            assert [d["code"] for d in control["diagnostics"]] == [
                "W_MAGNIFIER_FALLBACK"
            ]

        rate = DATE_FX[start]
        ledger = []
        for lot in broker["trades"]:
            entry, exit_price, qty = (
                lot["entryPrice"],
                lot["exitPrice"],
                abs(lot["qty"]),
            )
            assert qty > 0 and entry > 0 and exit_price > 0
            assert start <= lot["entryTime"] <= lot["exitTime"] < end
            assert lot["id"] in ("Long", "Short")
            for value, multiplier in ((qty, 1000), (entry, scale), (exit_price, scale)):
                scaled = value * multiplier
                assert math.isclose(scaled, round(scaled), rel_tol=0, abs_tol=1e-7)
            side = 1 if lot["id"] == "Long" else -1
            gross = side * (exit_price - entry) * qty * rate
            fee = (entry + exit_price) * qty * FEE * rate
            assert math.isclose(lot["profit"], gross - fee, rel_tol=0, abs_tol=1e-7)
            ledger.append(
                [
                    lot["entryTime"],
                    lot["exitTime"],
                    lot["id"],
                    qty,
                    entry,
                    exit_price,
                    gross,
                    fee,
                    lot["profit"],
                ]
            )
        assert ledger
        assert broker["equity"][0]["equity"] == CAPITAL
        last_pos = broker["position"][-1]
        results.append(
            {
                "market": market,
                "start": start,
                "end": end,
                "FX": rate,
                "source_sha256": SOURCE_SHA,
                "compiled_source_sha256": digest(code.encode()),
                "feed_sha256": digest(raw),
                "source_input_sha256": [
                    feed["raw_trade_sha256"],
                    feed["official_minute_sha256"],
                ],
                "chart_bars": len(chart),
                "lower_bars": len(lower),
                "fallback_diagnostics": 0,
                "flat_bars": int(flat),
                "flat_diagnostics": diagnostics,
                "complete_feed_matches_both_api_entrypoints": True,
                "empty_leg_guard_matches_original_ledger": True,
                "last_position": last_pos,
                "orders_by_kind": dict(
                    Counter(o["direction"] for o in broker["orders"])
                ),
                "ledger_checks": ledger,
            }
        )
    assert len({(row["market"], row["start"]) for row in results}) == 4
    receipt = {
        "runtime_binary_sha256": RUNTIME_SHA,
        "rates_inputs_sha256": digest(rate_bytes),
        "incomplete_feed_detected": True,
        "runs": results,
    }
    (work / "round8-fx-replay.json").write_text(
        json.dumps(receipt, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf8",
        newline="\n",
    )


if __name__ == "__main__":
    run(Path(__file__).resolve().parent)
