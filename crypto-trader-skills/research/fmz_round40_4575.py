"""Verify #4575 chart decisions, source orders, and recorded minute bracket paths."""

import math
import re
import sys
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

SOURCE = "7ab30491c8cbd0f8f6e71f80e01362f7fdc65f9ee9e00893cca5ea0f74c6ba01"
BEGIN, END = map(date_ms, ("2023-08-28", "2023-09-27"))
CAPITAL = 1_000_000
FEE = Decimal(".00075")
GROUPS = {
    "atr": "atr",
    "long stop": "longStopPrice",
    "short stop": "shortStopPrice",
    "bull setup": "validHammer ? 1 : 0",
    "bear setup": "validStar ? 1 : 0",
    "long flag": "validLong ? 1 : 0",
    "short flag": "validShort ? 1 : 0",
}
REQUEST = 'conversionCurrencyRate = security(symbol=syminfo.type == "forex" ? "BTC_USDT:swap" : "BTC_USDT:swap", resolution="D", expression=close)'


def programs(document):
    assert sha256(document) == SOURCE
    fence = chr(96) * 3
    (source,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    body, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert count == 1 and body.count("// @version=4") == 1
    body = body.replace("// @version=4", "//@version=4", 1)
    assert body.count(REQUEST) == 1 and body.count("conversionCurrencyRate") == 2
    # The conversion rate can change the alert quantity text and its display.
    # No computed AutoView quantity is passed to either entry order.
    orders = [
        x
        for x in body.splitlines()
        if x.startswith(("strategy.entry", "strategy.exit"))
    ]
    assert len(orders) == 4 and not any("tradePositionSize" in x for x in orders)
    instrumented = body + "".join(
        f'\nplot({expr}, "audit {label}")' for label, expr in GROUPS.items()
    )
    return (
        body,
        instrumented,
        instrumented.replace(REQUEST, "conversionCurrencyRate = 1.0", 1),
    )


def witnesses(bars):
    tr, states = [], []
    atr = None
    for i, (_, opening, high, low, close, _) in enumerate(bars):
        if not i:
            tr.append(high - low)
            states.append((None, 0, 0, None, None))
            continue
        previous = bars[i - 1]
        tr.append(max(high - low, abs(high - previous[4]), abs(low - previous[4])))
        if i == 13:
            atr = math.fsum(tr) / 14
        elif i > 13:
            atr = (13 * atr + tr[-1]) / 14
        if atr is None:
            states.append((None, 0, 0, None, None))
            continue
        allowed = 0 <= high - low <= 3 * atr and opening != close
        long = int(allowed and min(opening, close) >= high - (high - low) * 0.333)
        short = int(allowed and max(opening, close) <= low + (high - low) * 0.333)
        states.append(
            (
                atr,
                long,
                short,
                min(low, previous[3]) - atr,
                max(high, previous[2]) + atr,
            )
        )
    return states


def level(price, tick, up):
    return (price / tick).to_integral_value(
        rounding=ROUND_CEILING if up else ROUND_FLOOR
    ) * tick


def position_path(lot, minutes, tick):
    side = lot["side"]
    # For buys a lower limit preserves price protection; for sells a higher one.
    limit = level(lot["target"], tick, side > 0)
    protective = level(lot["stop"], tick, side < 0)
    for stamp, begin, high, low, _, vol in minutes:
        opening, high, low = (Decimal(str(v)) for v in (begin, high, low))
        limit_gap = (opening - limit) * side >= 0
        stop_gap = (opening - protective) * side <= 0
        assert not (limit_gap and stop_gap)
        if limit_gap or stop_gap:
            assert vol > 0
            return stamp, opening, "target gap" if limit_gap else "stop gap"
        may_take = high >= limit if side > 0 else low <= limit
        may_stop = low <= protective if side > 0 else high >= protective
        assert not (may_take and may_stop), (stamp, lot)
        if may_take or may_stop:
            assert vol > 0
            return (
                stamp,
                limit if may_take else protective,
                "target" if may_take else "stop",
            )
    return None


def settle(chart, minutes, states, tick):
    armed = None
    pending = None
    flags, entry, exits = [], [], []
    beginning_closed_at_open = []
    for i, bar in enumerate(chart):
        stamp, opening, _, _, close, _ = bar
        if pending:
            assert armed is None and len(minutes[i * 120 : (i + 1) * 120]) == 120
            assert (
                minutes[i * 120][0] == stamp
                and minutes[i * 120][1] == opening
                and minutes[i * 120][5] > 0
            )
            armed = {
                **pending,
                "time": stamp,
                "price": Decimal(str(opening)),
                "index": i,
            }
            entry.append(
                {
                    "id": "Long" if pending["side"] > 0 else "Short",
                    "bar_index": i,
                    "time": stamp,
                    "price": opening,
                }
            )
            pending = None
        if armed and armed["index"] < i:
            # The source issues brackets on the first completed chart bar with an open position.
            exit_fill = position_path(armed, minutes[i * 120 : (i + 1) * 120], tick)
            if exit_fill:
                exit_time, exit_price, kind = exit_fill
                initial = armed["price"]
                gross = (exit_price - initial) * armed["side"]
                commission = (exit_price + initial) * FEE
                exits.append(
                    {
                        "entryTime": armed["time"],
                        "exitTime": exit_time,
                        "dir": armed["side"],
                        "qty": 1,
                        "entryPrice": float(initial),
                        "exitPrice": float(exit_price),
                        "commission": float(commission),
                        "profit": float(gross - commission),
                        "entry_bar": armed["index"],
                        "exit_bar": i,
                        "trigger": kind,
                        "source_stop": float(armed["stop"]),
                        "source_target": float(armed["target"]),
                    }
                )
                if exit_time == stamp:
                    beginning_closed_at_open.append(i)
                armed = None
        _, buy, sell, ls, ss = states[i]
        assert buy + sell <= 1
        flags.append((int(bool(buy and not armed)), int(bool(sell and not armed))))
        if not armed and (buy or sell):
            side = buy - sell
            stop = Decimal(str(ls if buy else ss))
            target = 2 * Decimal(str(close)) - stop
            pending = {"side": side, "stop": stop, "target": target}
    return {
        "entries": entry,
        "settled": exits,
        "flags": flags,
        "unsettled": int(armed is not None),
        "exit_open_gaps": beginning_closed_at_open,
    }


def report_history(strategy):
    return {k: strategy[k] for k in ("orders", "trades", "position", "equity")}


def near(a, b):
    return math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-8)


def replay(engine, program_variants, symbol, chart, minutes, btc_daily):
    def encode(rows):
        return [dict(zip(FIELDS, x, strict=True)) for x in rows]

    ticks = Decimal(".1") if symbol == "BTCUSDT" else Decimal(".01")
    metadata = {
        "minMove": 1,
        "priceScale": int(1 / ticks),
        "minContract": ".001",
        "quantityStep": ".001",
        "pointValue": 1,
        "currency": "USDT",
    }
    frames = {f"BTC_USDT:swap:{tag}": btc_daily for tag in ("D", "1D", "1440")}
    frames["$chart"] = metadata
    opts = {
        "chart_timeframe": "120",
        "chart_symbol": f"BINANCE:{symbol}",
        "request_bars": frames,
    }
    native = [engine.run_script(p, encode(chart), **opts) for p in program_variants]
    assert all(
        not x["diagnostics"] and not x["strategy"]["diagnostics"] for x in native
    )
    receipts = [report_history(r["strategy"]) for r in native]
    assert receipts[0] == receipts[1] == receipts[2]
    assert (
        native[0]["alerts"] == native[1]["alerts"]
        and native[1]["alerts"] != native[2]["alerts"]
    )
    plots = [
        {
            p["title"][6:]: p["values"]
            for p in n["plots"]
            if p["title"].startswith("audit ")
        }
        for n in native[1:]
    ]
    assert plots[0] == plots[1]
    state = witnesses(chart)
    for i, (atr, buy, sell, ls, ss) in enumerate(state):
        p = plots[0]
        if atr is None:
            assert p["atr"][i] is None
        else:
            assert (
                near(p["atr"][i], atr)
                and near(p["long stop"][i], ls)
                and near(p["short stop"][i], ss)
            )
        assert (p["bull setup"][i], p["bear setup"][i]) == (buy, sell)
    result = settle(chart, minutes, state, ticks)
    plots_flags = list(zip(plots[0]["long flag"], plots[0]["short flag"], strict=True))
    assert result["flags"] == plots_flags, (
        symbol,
        [
            (i, a, b)
            for i, (a, b) in enumerate(zip(result["flags"], plots_flags, strict=True))
            if a != b
        ][:6],
    )
    native_orders = [
        x for x in receipts[0]["orders"] if x["direction"].endswith(("long", "short"))
    ]
    assert all(
        (a["id"], a["bar_index"], a["time"], a["price"], 1)
        == (b["id"], b["barIndex"], b["time"], b["price"], b["qty"])
        for a, b in zip(result["entries"], native_orders, strict=True)
    )
    for trade, prior in zip(result["settled"], receipts[0]["trades"], strict=True):
        assert (
            trade["entry_bar"],
            trade["exit_bar"],
            trade["entryPrice"],
            trade["qty"] * trade["dir"],
        ) == (
            prior["entryBarIndex"],
            prior["exitBarIndex"],
            prior["entryPrice"],
            prior["qty"],
        )
        assert (
            abs(Decimal(str(trade["exitPrice"])) - Decimal(str(prior["exitPrice"])))
            <= ticks
        )
    assert round(abs(receipts[0]["position"][-1]["size"])) == result["unsettled"]
    result.update(
        {
            "market": symbol,
            "independent_chart_bars": len(chart),
            "validated_minute_bars": len(minutes),
            "native_closed_lots": len(receipts[0]["trades"]),
        }
    )
    del result["flags"]
    return result


def main(document, augmented_august, september, quarters, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    manifest, cases = [], []
    variants = programs(document)
    btc_daily = None
    for market in ("BTCUSDT", "ETHUSDT"):
        minute_files = [
            *verified_archives(augmented_august, market, "1m", ("2023-08",), manifest),
            *verified_archives(september, market, "1m", ("2023-09",), manifest),
        ]
        minute = prices(minute_files, BEGIN, END, 60_000)
        quarter_files = verified_archives(
            quarters, market, "15m", ("2023-08", "2023-09"), manifest
        )
        chart = aggregate(prices(quarter_files, BEGIN, END, 900_000), 8)
        assert all(
            a[:5] == b[:5] for a, b in zip(aggregate(minute, 120), chart, strict=True)
        )
        if market == "BTCUSDT":
            btc_daily = [
                dict(zip(FIELDS, v, strict=True)) for v in aggregate(chart, 12)
            ]
            assert len(btc_daily) == (END - BEGIN) // DAY
        assert btc_daily
        cases.append(replay(pine_compat, variants, market, chart, minute, btc_daily))
    common = {
        "id": 4575,
        "group": "FMZ Pine v4 · Confirmed hammers and stars",
        "period": "2023-08-28 to 2023-09-27 UTC exclusive",
        "currency": "USDT",
        "interval": "2h with 1m exits",
        "archive_interval": "2h",
        "exit": "Authored ATR stop and 1R target",
        "pine_source_version": "4",
        "order_family": "Next-open market entry plus delayed named bracket",
    }
    results = [
        {
            **common,
            "market": c["market"],
            **ledger_metrics(c["settled"], CAPITAL, c["unsettled"]),
        }
        for c in cases
    ]
    results.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [t for c in cases for t in c["settled"]],
                2 * CAPITAL,
                sum(c["unsettled"] for c in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ #4575 native chart plus independent minute settlement",
            "source_sha256": SOURCE,
            "pine_engine_sha256": ENGINE_SHA,
            "data_archives": manifest,
            "notes": {
                "source": "Repaired only the spaced Pine version marker. Binance BTC futures daily candles supply the source conversion variable. Comparing against a fixed conversion control proves that conversion affects alert text, and no backtest order receives the alert's position size.",
                "model": "Confirmed source 2h gates, one base-unit next-open entries, and named stops and targets armed after the first close with an open position. All 2h chart OHLC values agree between official 15m and 1m sources. Exit prices represent the first legally rounded level reached or the first trade open that crosses it.",
                "costs": "The archive doesn't declare fees. Closed lots carry a 0.075% per-side overlay. No measured spread, market impact or funding is included.",
            },
            "coverage": [
                [
                    4575,
                    "Tested · BTC alias recoverable and real minute bracket chronology",
                    "Preserved the published stop and target rules and verified ATR, candle pattern gates, actual next opens, legal bracket ticks and the complete independently reconciled BTC/ETH ledger.",
                ]
            ],
            "cases": cases,
            "results": results,
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
