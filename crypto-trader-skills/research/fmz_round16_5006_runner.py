"""Probe the archived FMZ #5006 GBP-account, ten-minute signal strategy."""

import json
import math
import re
import sys
from collections import Counter, deque
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_3604 import INPUTS, near, options_for, pine_compat, sha256

DAY = 86_400_000
BAR = 600_000
CAPITAL = 1_000_000
FEE_OVERLAY = 0.00075

OBSERVER = """
plot(rsiUp, title="Observed average gain")
plot(rsiDown, title="Observed average loss")
plot(tradeDirection ? 1 : 0, title="Observed direction")
"""


def sources():
    raw = (ROOT / "source-5006.md").read_bytes()
    assert (
        sha256(raw)
        == "75ccb16d13396df5b7fa13ad7279aa164c6f8451f4dbd27ee6ca78f19065d42a"
    )
    (code,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    archive, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", code)
    assert count == 1
    no_op = """if (useTS and not useTSO) // without offset
    strategy.exit("XSL", from_entry = "Buy", trail_points = tslPoints)
    strategy.exit("XSS", from_entry = "Sell", trail_points = tslPoints)
"""
    assert archive.count(no_op) == 1
    legacy = archive.replace(no_op, "")
    code = legacy
    replacements = (
        ("//@version=2", "//@version=5", 1),
        (
            'input(defval = open, title = "RSI Source")',
            'input.source(defval = open, title = "RSI Source")',
            1,
        ),
        ("input(defval = false,", "input.bool(defval = false,", 3),
        ("input(defval = true,", "input.bool(defval = true,", 1),
        ("input(defval = 8,", "input.int(defval = 8,", 1),
        ("input(defval = 34,", "input.int(defval = 34,", 1),
        ("input(defval = 25,", "input.int(defval = 25,", 1),
        ("input(defval = 120,", "input.int(defval = 120,", 1),
        ("input(defval = 20,", "input.int(defval = 20,", 1),
        ("sum(exp,", "math.sum(exp,", 1),
        ("rma(", "ta.rma(", 2),
        ("change(", "ta.change(", 2),
        ("max(", "math.max(", 1),
        ("min(", "math.min(", 1),
        ("sma(", "ta.sma(", 1),
        ("tradeDirection ? green : red", "tradeDirection ? color.green : color.red", 1),
        ("color = silver,  linewidth = 1", "color = color.silver,  linewidth = 1", 2),
        (
            "color = purple, linewidth = 2, style = line, transp = 50",
            "color = color.new(color.purple, 50), linewidth = 2, style = plot.style_line",
            1,
        ),
        (
            "color = silver, linewidth = 1, style = area, transp = 70",
            "color = color.new(color.silver, 70), linewidth = 1, style = plot.style_area",
            1,
        ),
        (
            "long = true, when = goLong()",
            "direction = strategy.long, when = goLong()",
            1,
        ),
        (
            "long = false, when = goShort()",
            "direction = strategy.short, when = goShort()",
            1,
        ),
    )
    for old, new, count in replacements:
        assert code.count(old) == count, (old, count)
        code = code.replace(old, new)
    return archive, legacy, code


def fx_rates():
    raw = (ROOT / "5006-kraken-fx-rates.json").read_bytes()
    digest = sha256(raw)
    assert digest == "23d9497e0de8b6fddbd9a8aaeb1f31e3283392ced2d96aa78dc38dfa3050e15a"
    rates = {time: float(close) for time, close in json.loads(raw)}
    assert list(rates) == list(range(1_785_542_400_000, 1_793_491_200_000 + DAY, DAY))
    assert all(rate > 0 for rate in rates.values())
    data = {
        "schemaVersion": 1,
        "pairs": [
            {
                "from": "USDT",
                "to": "GBP",
                "rates": [
                    {"effectiveTime": time, "rate": rate}
                    for time, rate in rates.items()
                ],
            }
        ],
    }
    return digest, rates, data


def sample(name, checksum, take=None):
    raw = (ROOT / name).read_bytes()
    assert sha256(raw) == checksum
    envelope = json.loads(raw)
    keys = ("time", "open", "high", "low", "close", "volume")
    chart = [dict(zip(keys, row, strict=True)) for row in envelope["intrabar"][:take]]
    assert [bar["time"] for bar in chart] == list(
        range(envelope["from"], envelope["from"] + BAR * len(chart), BAR)
    )
    return envelope["symbol"], envelope["from"], envelope["to"], chart


def probe():
    versions = sources()
    _, rates, fx = fx_rates()
    name, checksum = next(iter(INPUTS.items()))
    market, start, _, chart = sample(name, checksum, 288)
    assert rates[start] > 0
    options = options_for(market)
    options["chart_timeframe"] = "10"
    options["request_bars"]["$currencyRates"] = fx
    receipt = {}
    for label, source in zip(
        ("archive", "legacy", "migrated", "observer"),
        (*versions, versions[-1] + OBSERVER),
        strict=True,
    ):
        try:
            receipt[label] = pine_compat.run_script(source, chart, **options)
        except ValueError as failure:
            receipt[label] = {"exception": str(failure).splitlines()}
    (ROOT / "5006-probe.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf8"
    )


def oracle(chart):
    open_prices = [bar["open"] for bar in chart]
    recent = deque(maxlen=34)
    average_gain = average_loss = 0.0
    rsis, mas, gains, losses, directions = [None], [None], [None], [None], [False]
    for i, (previous, current) in enumerate(pairwise(open_prices), 1):
        delta = current - previous
        gain, loss = max(0.0, delta), max(0.0, -delta)
        if i <= 8:
            average_gain += gain / 8
            average_loss += loss / 8
        else:
            average_gain = (7 * average_gain + gain) / 8
            average_loss = (7 * average_loss + loss) / 8
        if i >= 8:
            rsi = (
                100.0
                if average_loss == 0
                else 100 - 100 / (1 + average_gain / average_loss)
            )
            recent.append(rsi - 50)
            rsis.append(rsi - 50)
            gains.append(average_gain)
            losses.append(average_loss)
        else:
            rsis.append(None)
            gains.append(None)
            losses.append(None)
        ma = math.fsum(recent) / 34 if len(recent) == 34 else None
        mas.append(ma)
        directions.append(ma is not None and ma <= 0)
    return rsis, mas, gains, losses, directions


def verify_signals(archive, observed, reference):
    actual = [p["values"] for p in (*archive["plots"], *observed["plots"][-3:])]
    for label, calculated, native in zip(
        ("RSI", "SMA of RSI", "gain", "loss", "direction"),
        reference,
        actual,
        strict=True,
    ):
        for i, (a, b) in enumerate(zip(calculated, native, strict=True)):
            try:
                near(a, b)
            except AssertionError as failure:
                raise AssertionError(f"{label} bar {i}: {a} versus {b}") from failure


def trade_id(side):
    assert side in (-1, 1)
    return "Buy" if side == 1 else "Sell"


def audit_ledger(broker, chart, directions, rates):
    orders, trades = iter(broker["orders"]), iter(broker["trades"])
    side = pending = 0
    equity = CAPITAL
    size = entry_time = entry_price = 0
    was_long = False
    ledger = []

    def get_order(i, bar, expected_id, direction):
        fill = next(orders)
        assert fill["id"] == expected_id and fill["direction"] == direction, (
            i,
            fill,
            expected_id,
            direction,
        )
        assert fill["time"] == bar["time"] and fill["barIndex"] == i
        near(fill["price"], bar["open"])
        return fill

    for i, (bar, go_long) in enumerate(zip(chart, directions, strict=True)):
        stamp, price = bar["time"], bar["open"]
        fx = rates[stamp // DAY * DAY]
        if pending:
            assert pending != side
            if side:
                close = get_order(
                    i, bar, f"Close entry(s) order {trade_id(side)}", "strategy.close"
                )
                near(close["qty"], size)
                trade = next(trades)
                assert (
                    trade["id"] == trade_id(side)
                    and trade["entryTime"] == entry_time
                    and trade["exitTime"] == stamp
                )
                near(trade["qty"], side * size)
                near(trade["entryPrice"], entry_price)
                near(trade["exitPrice"], price)
                gross = side * size * (price - entry_price) * fx
                near(trade["profit"], gross)
                entry_fx = rates[entry_time // DAY * DAY]
                fee = FEE_OVERLAY * size * (entry_fx * entry_price + fx * price)
                ledger.append(
                    {
                        **trade,
                        "fx_entry": entry_fx,
                        "fx_exit": fx,
                        "fee_sensitivity": fee,
                        "after_fee_sensitivity": gross - fee,
                    }
                )
                equity += gross
            order = get_order(
                i,
                bar,
                trade_id(pending),
                "strategy.long" if pending == 1 else "strategy.short",
            )
            size = math.floor(equity * 0.10 / (price * fx) * 1000 + 1e-10) / 1000
            assert size > 0
            near(order["qty"], size)
            side, entry_time, entry_price = pending, stamp, price
        pending = (1 if go_long else -1) if go_long != was_long else 0
        was_long = go_long
    assert next(orders, None) is None and next(trades, None) is None
    terminal = broker["position"][-1] if broker["position"] else {"size": 0}
    near(terminal["size"], side * size)
    final = chart[-1]
    end_fx = rates[final["time"] // DAY * DAY]
    near(
        broker["equity"][-1]["equity"],
        equity + side * size * (final["close"] - entry_price) * end_fx,
    )
    return ledger, terminal


def replay():
    archive_source, legacy_source, migrated_source = sources()
    scripts = [
        pine_compat.compile_script(source)
        for source in (
            archive_source,
            legacy_source,
            migrated_source,
            migrated_source + OBSERVER,
        )
    ]
    engine_file = ROOT / "priced-runtime/pine_compat/pine_compat.pyd"
    engine = sha256(engine_file.read_bytes())
    assert engine == "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
    fx_hash, rates, fx = fx_rates()
    runs = []
    for name, checksum in INPUTS.items():
        market, start, end, chart = sample(name, checksum)
        assert start + BAR * len(chart) == end
        options = options_for(market)
        options["chart_timeframe"] = "10"
        options["request_bars"]["$currencyRates"] = fx
        archived, legacy, migrated, observed = [
            script.run(chart, **options) for script in scripts
        ]
        assert all(
            not result["diagnostics"]
            for result in (archived, legacy, migrated, observed)
        )
        base = migrated["strategy"]
        assert base == legacy["strategy"] == observed["strategy"]
        assert not base["diagnostics"] and base["equity"][0]["equity"] == CAPITAL
        archive_broker = archived["strategy"]
        assert {**archive_broker, "diagnostics": []} == base
        counts = dict(Counter(d["code"] for d in archive_broker["diagnostics"]))
        assert counts.keys() <= {"E_STRATEGY_EXIT_ENTRY"}
        assert [p["values"] for p in archived["plots"]] == [
            p["values"] for p in migrated["plots"]
        ]
        reference = oracle(chart)
        verify_signals(archived, observed, reference)
        ledger, ending = audit_ledger(archive_broker, chart, reference[-1], rates)
        runs.append(
            {
                "market": market,
                "start": start,
                "end": end,
                "bars": len(chart),
                "feed": name,
                "feed_sha256": checksum,
                "closed": len(ledger),
                "orders": len(base["orders"]),
                "ending_position": ending,
                "archived_noop_diagnostics": counts,
                "ledger": ledger,
            }
        )
    result = {
        "archived_source_sha256": sha256(archive_source.encode()),
        "migrated_source_sha256": sha256(migrated_source.encode()),
        "runtime_sha256": engine,
        "fx_sha256": fx_hash,
        "runs": runs,
    }
    (ROOT / "5006-replay.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["probe"]:
            probe()
        else:
            replay()
    except Exception:
        import traceback

        (ROOT / "5006-error.txt").write_text(traceback.format_exc(), encoding="utf8")
        raise
