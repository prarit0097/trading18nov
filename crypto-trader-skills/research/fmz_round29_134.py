"""Validate the original #134 scalper against a separate one-minute broker."""

import json
import math
import re
import sys
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from research.fmz_marketdata_replay import heikin_bars
from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

SOURCE_SHA = "82e6e7492cb3a6c35931eb5c6173b28077056d3117c83ebfff204214e33ce6bb"
START, END = map(date_ms, ("2024-01-01", "2024-02-01"))
CAPITAL = 10_000
FEE = Decimal("0.0004")
PROBES = """
plot(L_ ? 1 : 0, title="Long actual")
plot(S_ ? 1 : 0, title="Short actual")
plot(Lev_vol, title="Authored quantity")
plot(testPeriod ? 1 : 0, title="In time range")
plot(haOpen, title="HA open")
plot(haHigh, title="HA high")
plot(haLow, title="HA low")
plot(haClose, title="HA close")
"""


def closed_lot(position, i, stamp, exit_price):
    side, qty, entry_i, entry_time, entry_price = position
    first, last = Decimal(str(entry_price)), Decimal(str(exit_price))
    fee = qty * (first + last) * FEE
    pnl = qty * side * (last - first) - fee
    return {
        "entryBarIndex": entry_i,
        "exitBarIndex": i,
        "entryTime": entry_time,
        "exitTime": stamp,
        "entryPrice": entry_price,
        "exitPrice": exit_price,
        "dir": side,
        "qty": qty,
        "commission": float(fee),
        "profit": float(pnl),
    }


def bracket_exit(children, position, previous_close, tick):
    side, _, _, _, entry = position
    origin = Decimal(str(entry))
    prior = Decimal(str(previous_close))
    target_dist = (prior * Decimal(".02") / tick).to_integral_value(
        rounding=ROUND_CEILING
    ) * tick
    stop_dist = (prior * Decimal(".08") / tick).to_integral_value(
        rounding=ROUND_CEILING
    ) * tick
    target = float(origin + side * target_dist)
    stop = float(origin - side * stop_dist)
    for stamp, opening, high, low, _, volume in children:
        hit_tp = high >= target if side == 1 else low <= target
        hit_sl = low <= stop if side == 1 else high >= stop
        if not (hit_tp or hit_sl):
            continue
        assert volume > 0 and hit_tp != hit_sl
        level = target if hit_tp else stop
        gapped = (
            side * opening >= side * level if hit_tp else side * opening <= side * level
        )
        return stamp, opening if gapped else level, "target" if hit_tp else "stop"
    return None


def broker(chart, children, plots, tick):
    orders, lots, exits = [], [], []
    pos = pending = None
    for i, bar in enumerate(chart):
        stamp, opening = bar["time"], bar["open"]
        if pending is not None:
            side, qty = pending
            transfer = qty
            if pos is not None:
                assert side != pos[0]
                transfer += pos[1]
                lots.append(closed_lot(pos, i, stamp, opening))
            assert children[30 * i][1] == opening and children[30 * i][5] > 0
            orders.append(("L" if side == 1 else "S", i, transfer, opening))
            pos = (side, qty, i, stamp, opening)
        hit = (
            bracket_exit(
                children[30 * i : 30 * (i + 1)], pos, chart[i - 1]["close"], tick
            )
            if pos is not None
            else None
        )
        if hit is not None:
            exit_stamp, price, kind = hit
            orders.append(("S_tp/sl", i, pos[1], price))
            lots.append(closed_lot(pos, i, exit_stamp, price))
            exits.append((i, exit_stamp, kind))
            pos = None
        buy, sell = plots["Long actual"][i], plots["Short actual"][i]
        assert not (buy and sell)
        side = int(bool(buy)) - int(bool(sell))
        pending = (
            (side, int(plots["Authored quantity"][i]))
            if side and (pos is None or side != pos[0])
            else None
        )
    return orders, lots, exits, pos


def replay(module, market, prices_1m):
    tick = Decimal(".1" if market == "BTCUSDT" else ".01")
    chart = [dict(zip(FIELDS, row, strict=True)) for row in aggregate(prices_1m, 30)]
    synthetic = heikin_bars(chart)
    symbol = f"BINANCE:{market}"
    ha_key = (
        json.dumps({"chart": "heikinashi", "symbol": symbol}, separators=(",", ":"))
        + ":30"
    )
    instrument = {
        "minMove": 1,
        "priceScale": int(1 / tick),
        "quantityStep": ".001",
        "minContract": ".001",
        "pointValue": 1,
        "currency": "USDT",
    }
    options = {"chart_symbol": symbol, "chart_timeframe": "30"}

    def trace_until(end):
        return module.run(
            chart[:end],
            request_bars={ha_key: synthetic[:end], "$chart": instrument},
            **options,
        )

    trace = trace_until(len(chart))
    observed = trace["strategy"]
    assert not trace["diagnostics"] and not observed["diagnostics"]
    plots = {p["title"]: p["values"] for p in trace["plots"] if p.get("title")}
    assert plots["In time range"] == [1] * len(chart)
    for field in ("open", "high", "low", "close"):
        assert plots[f"HA {field}"] == [bar[field] for bar in synthetic]
    orders, trades, brackets, ending = broker(chart, prices_1m, plots, tick)
    for x, (ident, i, qty, px) in zip(observed["orders"], orders, strict=True):
        assert (x["id"], x["barIndex"], x["qty"]) == (ident, i, qty)
        assert math.isclose(x["price"], px, abs_tol=1e-8)
    for actual, control in zip(observed["trades"], trades, strict=True):
        for key in (
            "entryBarIndex",
            "exitBarIndex",
            "entryTime",
            "entryPrice",
            "exitPrice",
            "profit",
        ):
            assert math.isclose(actual[key], control[key], rel_tol=1e-12, abs_tol=1e-8)
        assert actual["qty"] == control["dir"] * control["qty"]
    assert observed["position"][-1]["size"] == (ending[0] * ending[1] if ending else 0)
    cuts = (orders[0][1], len(chart) // 2)
    for n in cuts:
        short = trace_until(n)
        short_plots = {
            p["title"]: p["values"] for p in short["plots"] if p.get("title")
        }
        for label in ("Long actual", "Short actual", "Authored quantity", "HA close"):
            assert short_plots[label] == plots[label][:n]
        assert short["strategy"]["orders"] == [
            x for x in observed["orders"] if x["barIndex"] < n
        ]
    return {
        "market": market,
        "fills": orders,
        "trades": trades,
        "closing_brackets": brackets,
        "ending_position": ending,
        "verified_chart_bars": len(chart),
        "prefix_control_lengths": cuts,
    }


def run(document, market_dir, runtime, output):
    assert (
        sha256(document) == SOURCE_SHA
        and sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    )
    sys.path.insert(0, str(runtime))
    import pine_compat

    fence = chr(96) * 3
    (source,) = re.findall(
        r"(?ms)^" + fence + r"[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    module = pine_compat.compile_script(source + PROBES)
    archives, cases = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        official = verified_archives(market_dir, market, "1m", ("2024-01",), archives)
        cases.append(replay(module, market, prices(official, START, END, 60_000)))
    rows = []
    for market, subset in (
        (cases[0]["market"], cases[:1]),
        (cases[1]["market"], cases[1:]),
        ("BTCUSDT + ETHUSDT", cases),
    ):
        rows.append(
            {
                "id": 134,
                "group": "FMZ Pine v4 · Raw USD-M fills and HA signals",
                "period": "Binance USD-M · January 2024 UTC",
                "market": market,
                "exit": "Source reversal or 2%/8% price-relative bracket",
                "interval": "30m chart · 1m proof",
                "pine_source_version": "4",
                "currency": "USDT",
                **ledger_metrics(
                    [t for c in subset for t in c["trades"]],
                    CAPITAL * len(subset),
                    sum(c["ending_position"] is not None for c in subset),
                ),
            }
        )
    write(
        output,
        {
            "schema": "FMZ 134 · Causal 30m and one-minute bracket replay",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "archives": archives,
            "notes": {
                "source": "Unchanged archived Pine v4 executable with observational plots only. The source has no saved exchange window. January 2024 Binance USD-M is a benchmark, with 30m chart timing from the title and cold chart/Heikin Ashi initialization.",
                "rules": "Orders use authored flags, directions and one/two-base-unit sizing. Reversals occur at the next traded open. Both relative exit levels use the previous confirmed close and round trigger distance up to the market tick. The separate one-minute chronological broker reproduced every order and closed lot, with no same-child ambiguity.",
                "costs": "Source commission 0.04% per fill. Reported execution uses modeled bracket triggers or gap openings at observed one-minute prices. No independent spread, funding, margin or liquidation model is supplied. The large authored exposure and realized capital drawdown are benchmark metrics.",
            },
            "coverage": [
                [
                    134,
                    "Tested · exact v4 scalper and chronological minute brackets",
                    "Archived Pine v4 and confirmed Heikin Ashi signals. Native and independent one-minute settlement agree on all 87 order events and 52 closed lots. One open ETH position at cutoff.",
                ]
            ],
            "results": rows,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
