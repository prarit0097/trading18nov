"""Verify FMZ #3315 on independent hourly crypto charts and 15m base bars."""

import itertools
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS

SOURCE_SHA = "93f6e23ca7a5c43ab0e401c21003a1d19d8d1e10a8a3f81cf30c427631ec2fd8"
FEEDS = {
    "BTCUSDT": "569b2abcf453888cd6900bda8dd42d0f1b20359888ed00166ebd22c38ca240cf",
    "ETHUSDT": "e2d40becd8b9e1056a4c17b1016ea9d03cb797b33d14bbb3d7a33e63beef5cfa",
}
CAPITAL = 300_000
FEE = 0.00075
HOUR = 3_600_000
OBSERVE = """
plot(buy_condition ? 1 : 0, title="Entry")
plot(sell_condition ? 1 : 0, title="Exit")
plot(stop_loss, title="Long stop")
plot(take_profit, title="Long target")
plot(twoxtake_profit, title="Long bracket activation")
plot(short_stop_loss, title="Short stop")
plot(d, title="Stochastic D")
plot(macd_line, title="MACD")
plot(signal_line, title="MACD signal")
"""


def averages(values, length, seed_mean=False):
    out = (
        [None] * (length - 1) + [math.fsum(values[:length]) / length]
        if seed_mean
        else []
    )
    alpha = 2 / (length + 1)
    for value in values[len(out) :]:
        out.append(value if not out else alpha * value + (1 - alpha) * out[-1])
    return out


def independent_signals(chart):
    close = [bar["close"] for bar in chart]
    fast, slow = (averages(close, n) for n in (5, 13))
    m_fast, m_slow = (averages(close, n, seed_mean=True) for n in (8, 21))
    macd = [None] * 20 + [a - b for a, b in zip(m_fast[20:], m_slow[20:], strict=True)]
    macd_signal = [None] * 20 + averages(macd[20:], 5, seed_mean=True)
    gains, losses = [], []
    for p, c in itertools.pairwise(close):
        gains.append(max(c - p, 0))
        losses.append(max(p - c, 0))
    gain = math.fsum(gains[:14]) / 14
    loss = math.fsum(losses[:14]) / 14
    rsi = [None] * 14
    for i in range(14, len(close)):
        if i > 14:
            gain = (13 * gain + gains[i - 1]) / 14
            loss = (13 * loss + losses[i - 1]) / 14
        rsi.append(100 - 100 / (1 + gain / loss) if loss else 100)
    stochastic_k = [None] * 13
    for i in range(13, len(close)):
        w = close[i - 13 : i + 1]
        low, high = min(w), max(w)
        assert high > low
        stochastic_k.append(100 * (close[i] - low) / (high - low))
    stochastic_d = [None] * 15 + [
        math.fsum(stochastic_k[i - 2 : i + 1]) / 3 for i in range(15, len(close))
    ]
    long_in = [
        int(
            i > 0
            and rsi[i] is not None
            and rsi[i] > 50
            and fast[i] > slow[i]
            and fast[i - 1] <= slow[i - 1]
        )
        for i in range(len(close))
    ]
    exit = [
        int(d is not None and s > f and ms is not None and m < ms and d > 60)
        for f, s, m, ms, d in zip(
            fast, slow, macd, macd_signal, stochastic_d, strict=True
        )
    ]
    return long_in, exit, stochastic_d


def check_execution(strategy, chart, groups, observed):
    long_gate, exit_gate, stochastic = independent_signals(chart)
    plots = {p["title"]: p["values"] for p in observed["plots"]}
    assert plots["Entry"] == long_gate
    assert plots["Exit"] == exit_gate
    for i, value in enumerate(stochastic):
        if value is not None:
            assert math.isclose(plots["Stochastic D"][i], value, abs_tol=1e-9)
    close = [b["close"] for b in chart]
    partials = []
    entry = None
    deferred_short = None
    cash = float(CAPITAL)
    held = 0.0
    open_lots = 0
    for order in strategy["orders"]:
        i, px, qty, kind = (order[k] for k in ("barIndex", "price", "qty", "id"))
        assert order["time"] == chart[i]["time"]
        if kind == "Pivot Up":
            assert long_gate[i] and held == 0 and px == close[i]
            signed_fill = qty
            entry = close[i]
            assert qty == math.floor((cash * 0.15 / px) * 1000) / 1000
            open_lots += 1
        elif kind == "Pivot Down":
            assert deferred_short == i and stochastic[i - 6] > 80 and px == close[i]
            signed_fill = -qty
            assert qty == math.floor((cash * 0.15 / px) * 1000) / 1000
            open_lots += 1
        elif kind == "Close entry(s) order Pivot Up":
            assert px == close[i] and math.isclose(held, qty, abs_tol=1e-9)
            assert exit_gate[i] or close[i] < plots["Long stop"][i - 1]
            signed_fill = -qty
            deferred_short = i
            open_lots -= 1
        else:
            assert kind == "Exit Partial Longs" and held > 0
            assert qty == math.floor(held * 500 + 1e-8) / 1000
            prior = max(k for k in range(i) if close[k] >= entry * 1.06)
            stop = math.floor(close[prior] * 0.985 * 100) / 100
            target = math.ceil(close[prior] * 1.015 * 100) / 100
            assert math.isclose(
                plots["Long stop"][i - 1], close[prior] * 0.985, abs_tol=1e-8
            )
            assert math.isclose(
                plots["Long target"][i - 1], close[prior] * 1.015, abs_tol=1e-8
            )
            for sub in groups[i]["bars"]:
                if sub["low"] <= stop or sub["high"] >= target:
                    assert (sub["low"] <= stop) != (sub["high"] >= target)
                    if sub["low"] <= stop:
                        assert px == min(stop, sub["open"]), (
                            i,
                            prior,
                            close[prior],
                            stop,
                            target,
                            px,
                            sub["open"],
                        )
                    else:
                        assert px == max(target, sub["open"])
                    break
            else:
                raise AssertionError("Missing hourly exit in 15-minute prices")
            partials.append(
                {
                    "chart_index": i,
                    "fill": px,
                    "parent_bracket_index": prior,
                    "base_bar": sub["time"],
                    "stop": stop,
                    "target": target,
                }
            )
            signed_fill = -qty
        cash -= signed_fill * px
        held += signed_fill
        if abs(held) < 1e-9:
            held = 0.0
    assert open_lots == 1
    assert math.isclose(held, strategy["position"][-1]["size"], abs_tol=1e-9)
    assert math.isclose(
        cash + held * close[-1], strategy["equity"][-1]["equity"], abs_tol=1e-7
    )
    ledger = []
    for lot in strategy["trades"]:
        qty = abs(lot["qty"])
        side = 1 if lot["qty"] > 0 else -1
        ep, xp = lot["entryPrice"], lot["exitPrice"]
        gross = side * qty * (xp - ep)
        assert math.isclose(lot["profit"], gross, abs_tol=1e-8)
        assert ep == close[lot["entryBarIndex"]]
        fee = FEE * qty * (ep + xp)
        ledger.append(
            {**lot, "dir": side, "qty": qty, "commission": fee, "profit": gross - fee}
        )
    return ledger, partials


def replay(engine, source, stripped, chart, groups, market):
    options = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "60",
        "request_bars": {
            "$chart": {
                "minMove": 1,
                "priceScale": 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
        },
    }
    comparison = engine.run_script(stripped, chart, **options)["strategy"]
    for sentinel in (15.0, 150.0):
        dummy = [
            {
                **row,
                "open": sentinel,
                "high": sentinel,
                "low": sentinel,
                "close": sentinel,
            }
            for row in chart
        ]
        test = {**options, "request_bars": {**options["request_bars"], "VIX:60": dummy}}
        assert engine.run_script(source, chart, **test)["strategy"] == comparison
    based = stripped.replace(
        "max_labels_count=500)", "max_labels_count=500, use_bar_magnifier=true)"
    )
    witness = engine.run_script(
        based + OBSERVE,
        chart,
        **options,
        magnifier_bars={"schemaVersion": 1, "chartBars": groups},
    )
    assert witness["strategy"] == comparison
    assert not witness["diagnostics"]
    ledger, partials = check_execution(comparison, chart, groups, witness)
    return {
        "market": market,
        "bars": len(chart),
        "fills": comparison["orders"],
        "legs": ledger,
        "partial_checks": partials,
        "ending_position": comparison["position"][-1],
        "ending_equity": comparison["equity"][-1]["equity"],
    }


def metrics(cases):
    legs = [leg for scope in cases for leg in scope["legs"]]
    totals = ledger_metrics(legs, len(cases) * CAPITAL, len(cases))
    groups = defaultdict(lambda: [0.0, 0.0])
    for case in cases:
        for leg in case["legs"]:
            pnl = groups[case["market"], leg["entryTime"]]
            pnl[0] += leg["profit"] + leg["commission"]
            pnl[1] += leg["profit"]
    totals["trades"] = len(groups)
    totals["gross_wins"] = sum(gross > 0 for gross, net in groups.values())
    totals["fee_wins"] = totals["net_wins"] = sum(
        net > 0 for gross, net in groups.values()
    )
    return totals


def run(work, feeds, engine_root, output):
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    path = work / "source-3315.md"
    assert sha256(path) == SOURCE_SHA
    (source,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", path.read_text(encoding="utf-8")
    )
    stripped, n = re.subn(r"(?m)^vixClose = .*\n", "", source)
    assert n == 1 and re.findall(r"\bvixClose\b", stripped) == ["vixClose"]
    assert "//plot(vixClose" in stripped
    cases = []
    for market, digest in FEEDS.items():
        path = feeds / f"4671-authored-{market}.json"
        assert sha256(path) == digest
        raw = read(path)
        chart = [dict(zip(FIELDS, row, strict=True)) for row in raw["chart"]]
        base = [dict(zip(FIELDS, row, strict=True)) for row in raw["intrabar"]]
        assert [x["time"] for x in chart] == list(range(raw["from"], raw["to"], HOUR))
        assert [x["time"] for x in base] == list(
            range(raw["from"], raw["to"], HOUR // 4)
        )
        groups = [
            {"chartBarIndex": i, "bars": base[i * 4 : i * 4 + 4]}
            for i in range(len(chart))
        ]
        for row, group in zip(chart, groups, strict=True):
            parts = group["bars"]
            assert (row["open"], row["close"]) == (parts[0]["open"], parts[-1]["close"])
            assert row["high"] == max(b["high"] for b in parts) and row["low"] == min(
                b["low"] for b in parts
            )
        cases.append(replay(engine, source, stripped, chart, groups, market))
    meta = {
        "id": 3315,
        "group": "FMZ · Pine v5 · Hourly crypto research transfer",
        "archive_interval": "1h described",
        "interval": "1h",
        "currency": "USDT",
        "period": "Binance USD-M · 2023-09-08 to 2023-10-08 UTC exclusive",
        "exit": "Source market closes and 50% partial brackets",
    }
    results = [{**meta, "market": c["market"], **metrics([c])} for c in cases]
    results.append({**meta, "market": "BTCUSDT + ETHUSDT", **metrics(cases)})
    write(
        output,
        {
            "schema": "FMZ 3315 · Hourly source-equivalence and 15-minute fill checks",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "feeds_sha256": FEEDS,
            "notes": {
                "scope": "The author describes SPY 1-hour trading and supplies no saved historical case. The research uses BTC and ETH hourly perpetual candles and full 15-minute bases with all other source conditions unchanged. This is a crypto transfer test.",
                "vix": "The VIX query result is only mentioned in an inactive plot comment. Two intentionally distinct sentinel values were used solely for regression controls. Both outputs exactly match the no-query run; no VIX market data enters any performance row.",
                "broker": "Preserves archived process_orders_on_close, 15% equity sizing, 300,000 USDT starting equity and the zero native commission. A separate 0.075% per-side overlay uses the same fills. Realized drawdown includes all partials. Win rates use fully settled positions; the remaining long and short have no partial cashflow.",
                "validation": "An independent reconstruction reproduces the EMA/RSI buy gate, EMA/MACD/Stochastic exit gate, opening and closing cash, partial quantities and distinct 15-minute first-touch bracket prices. Funding and execution cost are outside the fee overlay.",
            },
            "coverage": [
                [
                    3315,
                    "Tested · Hourly crypto transfer and partial bracket verification",
                    "Original SPY order logic reproduced on explicit BTC/ETH research window. Two sentinel controls prove the dormant VIX request has no order effect. Independent 15-minute first touches reconcile partial fill prices.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
