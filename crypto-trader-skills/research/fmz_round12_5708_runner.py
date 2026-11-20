"""Validate both the migrated FMZ signals and historical market order path."""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from observe import OBSERVER, as_objects, digest, migrate, pine_compat

DAY = 86_400_000
HOUR = 3_600_000
CAPITAL = 100_000
FEE_SENSITIVITY = 0.00075
PINNED_INPUTS = {
    "feed-BTCUSDT-60-10-2026-08-01.json": "a5755ee6025dfdcab4cfb9ac9b3aadbace660d5b55ff17506fcb6efded2e8c0f",
    "feed-BTCUSDT-60-10-2026-09-01.json": "3a81c4ede2336c5d0c73c8046370f4c57447d900591dbc4af98c0f7231610a92",
    "feed-ETHUSDT-60-10-2026-08-01.json": "93dc2ba45c253f976e815145566c72b4479912f4af8d3faa8514d764a4061697",
    "feed-ETHUSDT-60-10-2026-09-01.json": "8ee222940f301fc9b88523d9c873d34323aa4bbf9656eeda3b4c66f7558f238a",
}


def price_signals(chart):
    highs = [c["high"] for c in chart]
    lows = [c["low"] for c in chart]
    # `highest(high, 22)[1]` and its low counterpart need 22 prior bars.
    signals = [0] * min(22, len(chart))
    for i, bar in enumerate(chart[22:], 22):
        price = (bar["high"] + bar["low"] + bar["close"]) / 3
        prior_high = max(highs[i - 22 : i])
        prior_low = min(lows[i - 22 : i])
        guard_high = max(highs[i - 15 : i - 1])
        guard_low = min(lows[i - 15 : i - 1])
        long_signal = price > prior_high > guard_high
        short_signal = price < prior_low < guard_low
        assert not (long_signal and short_signal)
        signals.append(int(long_signal) - int(short_signal))
    return signals


def load_rates():
    raw = (ROOT / "coinbase-usdt-usd-daily.json").read_bytes()
    assert (
        digest(raw)
        == "dd53c721473b042052016cc617ba098fdc5835285da75bcd47e0f6b7b28751c2"
    )
    candles = sorted(json.loads(raw))
    times = [c[0] for c in candles]
    assert times == list(range(times[0], times[-1] + 86400, 86400))
    assert all(
        stamp % 86400 == 0 and low <= close <= high and low <= start <= high
        for stamp, low, high, start, close, _ in candles
    )
    rates = {(c[0] + 86400) * 1000: c[4] for c in candles}
    envelope = {
        "schemaVersion": 1,
        "pairs": [
            {
                "from": "USDT",
                "to": "USD",
                "rates": [
                    {"effectiveTime": time, "rate": rate}
                    for time, rate in rates.items()
                ],
            }
        ],
    }
    return rates, envelope, digest(raw)


def close_enough(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7), (
        actual,
        expected,
    )


def side_name(direction):
    assert direction in (-1, 1)
    return "Long" if direction == 1 else "Short"


def audit_orders_and_trades(broker, chart, signals, rates):
    orders = iter(broker["orders"])
    trades = iter(broker["trades"])
    settled_equity = CAPITAL
    position_size = 0
    position_side = 0
    position_start = 0
    position_price = 0
    pending = 0
    intrabar_reversals = 0
    ledger = []

    def fill(i, stamp, price, side, rate):
        nonlocal \
            settled_equity, \
            position_size, \
            position_side, \
            position_start, \
            position_price
        assert side != position_side
        if position_size:
            trade = next(trades)
            gross = position_side * position_size * (price - position_price) * rate
            close_enough(trade["profit"], gross)
            close_enough(abs(trade["qty"]), position_size)
            close_enough(trade["entryPrice"], position_price)
            close_enough(trade["exitPrice"], price)
            assert trade["id"] == side_name(position_side)
            assert trade["entryTime"] == position_start and trade["exitTime"] == stamp
            entry_rate = rates[position_start // DAY * DAY]
            fees = (
                FEE_SENSITIVITY
                * position_size
                * (position_price * entry_rate + price * rate)
            )
            ledger.append(
                {
                    **trade,
                    "fee_sensitivity": fees,
                    "after_fee_sensitivity": gross - fees,
                }
            )
            settled_equity += gross
        new_size = math.floor(settled_equity / (price * rate) * 1000 + 1e-10) / 1000
        assert new_size > 0
        order = next(orders)
        close_enough(order["price"], price)
        close_enough(order["qty"], new_size + position_size)
        assert (
            order["id"] == side_name(side)
            and order["barIndex"] == i
            and order["time"] == stamp
        )
        assert order["direction"] == "strategy." + side_name(side).lower()
        position_size, position_side, position_start, position_price = (
            new_size,
            side,
            stamp,
            price,
        )

    for i, (bar, signal) in enumerate(zip(chart, signals, strict=True)):
        stamp = bar["time"]
        rate = rates[stamp // DAY * DAY]
        if pending:
            fill(i, stamp, bar["open"], pending, rate)
            if signal and signal != position_side:
                high_nearer = bar["high"] - bar["open"] < bar["open"] - bar["low"]
                fill(i, stamp, bar["high" if high_nearer else "low"], signal, rate)
                intrabar_reversals += 1
        pending = signal if signal != position_side else 0
    assert next(orders, None) is None and next(trades, None) is None
    close_enough(broker["position"][-1]["size"], position_side * position_size)
    closing_bar = chart[-1]
    final_rate = rates[closing_bar["time"] // DAY * DAY]
    unrealized = (
        position_side
        * position_size
        * (closing_bar["close"] - position_price)
        * final_rate
    )
    close_enough(broker["equity"][-1]["equity"], settled_equity + unrealized)
    return ledger, intrabar_reversals


def verify_synthetic():
    sample = json.loads((ROOT / "synthetic-observed.json").read_bytes())
    broker = sample["complete"]["strategy"]
    no_callback = sample["no_on_fill"]["strategy"]
    signals = price_signals(sample["chart"])
    assert signals == [0] * 25 + [1, -1, 0]
    assert [x["price"] for x in broker["orders"]] == [130.0, 132.0]
    assert [x["price"] for x in no_callback["orders"]] == [130.0, 45.0]
    ledger, intrabar = audit_orders_and_trades(
        broker, sample["chart"], signals, {0: 0.98, DAY: 0.95}
    )
    assert len(ledger) == intrabar == 1


def verify_lower_control(
    program, options, chart, market, basename, outcome, references, incomplete
):
    first = basename.removeprefix(f"feed-{market}-60-10-")
    name = f"native-base-{market}-{first}"
    raw = (ROOT / name).read_bytes()
    assert digest(raw) == references[name]["sha256"]
    lower = as_objects(json.loads(raw))
    assert len(lower) == len(chart) * 4 == references[name]["15m_bars"]
    assert [b["time"] for b in lower] == list(
        range(chart[0]["time"], chart[-1]["time"] + HOUR, HOUR // 4)
    )
    groups = [
        {"chartBarIndex": i, "bars": lower[i * 4 : (i + 1) * 4]}
        for i in range(len(chart))
    ]
    for parent, group in zip(chart, groups, strict=True):
        bars = group["bars"]
        assert (
            bars[0]["open"] == parent["open"] and bars[-1]["close"] == parent["close"]
        )
        assert max(row["high"] for row in bars) == parent["high"]
        assert min(row["low"] for row in bars) == parent["low"]
        close_enough(math.fsum(row["volume"] for row in bars), parent["volume"])
    control = program.run(
        chart, **options, magnifier_bars={"schemaVersion": 1, "chartBars": groups}
    )
    assert control == outcome, (market, first, control["diagnostics"])
    if incomplete:
        broken = program.run(
            chart,
            **options,
            magnifier_bars={"schemaVersion": 1, "chartBars": groups[:-1]},
        )
        assert [d["code"] for d in broken["diagnostics"]] == ["W_MAGNIFIER_FALLBACK"]
    return {"name": name, "sha256": digest(raw), "bars": len(lower), "match": True}


def replay():
    engine_file = ROOT / "priced-runtime/pine_compat/pine_compat.pyd"
    engine_sha = digest(engine_file.read_bytes())
    assert (
        engine_sha == "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
    )
    source = migrate()
    rates, envelope, rate_hash = load_rates()
    verify_synthetic()
    program = pine_compat.compile_script(source)
    assert source.count("calc_on_order_fills=true") == 1
    lower_program = pine_compat.compile_script(
        source.replace(
            "calc_on_order_fills=true",
            "calc_on_order_fills=true, use_bar_magnifier=true",
        )
    )
    manifest = json.loads((ROOT / "5708-input-manifest.json").read_bytes())
    lower_refs = {entry["name"]: entry for entry in manifest["derived"]}
    cases = []
    for basename, reference_sha in PINNED_INPUTS.items():
        raw = (ROOT / basename).read_bytes()
        assert digest(raw) == reference_sha
        feed = json.loads(raw)
        market, start, end = feed["symbol"], feed["from"], feed["to"]
        chart = as_objects(feed["chart"])
        assert [b["time"] for b in chart] == list(range(start, end, HOUR))
        options = {
            "chart_symbol": f"BINANCE:{market}",
            "chart_timeframe": "60",
            "request_bars": {
                "$chart": {
                    "minMove": 1,
                    "priceScale": 10 if market == "BTCUSDT" else 100,
                    "pointValue": 1,
                    "quantityStep": "0.001",
                    "minContract": "0.001",
                    "currency": "USDT",
                },
                "$currencyRates": envelope,
            },
        }
        outcome = program.run(chart, **options)
        observed = pine_compat.run_script(source + OBSERVER, chart, **options)
        assert observed["strategy"] == outcome["strategy"]
        assert not outcome["diagnostics"], outcome["diagnostics"]
        assert not outcome["strategy"]["diagnostics"], outcome["strategy"][
            "diagnostics"
        ]
        signals = price_signals(chart)
        long_observed, short_observed = observed["plots"][-2:]
        for i, (long, short, side) in enumerate(
            zip(long_observed["values"], short_observed["values"], signals, strict=True)
        ):
            assert long == int(side == 1) and short == int(side == -1), (
                market,
                start,
                i,
                long,
                short,
                side,
            )
        broker = outcome["strategy"]
        ledger, intrabar = audit_orders_and_trades(broker, chart, signals, rates)
        lower = verify_lower_control(
            lower_program,
            options,
            chart,
            market,
            basename,
            outcome,
            lower_refs,
            not cases,
        )
        cases.append(
            {
                "source_sha256": digest(source.encode()),
                "feed": basename,
                "feed_sha256": reference_sha,
                "market": market,
                "start": start,
                "end": end,
                "chart_bars": len(chart),
                "long_signals": signals.count(1),
                "short_signals": signals.count(-1),
                "intrabar_reversals": intrabar,
                "official_15m_sensitivity": lower,
                "fills": len(broker["orders"]),
                "closed": len(ledger),
                "ending_position": broker["position"][-1],
                "ledger": ledger,
            }
        )
    output = {
        "fx_sha256": rate_hash,
        "engine_sha256": engine_sha,
        "inputs": manifest,
        "cases": cases,
    }
    (ROOT / "replay-5708.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        replay()
    except Exception:
        import traceback

        (ROOT / "replay-5708-error.txt").write_text(
            traceback.format_exc(), encoding="utf8"
        )
        raise
