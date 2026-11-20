"""Isolated source-equivalence and actual Binance replay for FMZ #2864."""

import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "priced-runtime"))
import pine_compat

DAY = 86_400_000
CAPITAL = 1000
FEE_OVERLAY = 0.00075


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def migrate():
    raw = (ROOT / "source-2864.md").read_bytes()
    assert (
        sha256(raw)
        == "bf53b40fbca165ea4ddc50c9a3c254e59e8ae8cc997a3df4776e3e730e534d08"
    )
    (archived,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    code, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", archived)
    assert count == 1
    replacements = (
        ("//@version=4", "//@version=5"),
        (
            'input(title="Resolution", type=input.resolution, defval="")',
            'input.timeframe(title="Resolution", defval="")',
        ),
        (
            'input(20, title="RSI Length", type=input.integer)',
            'input.int(20, title="RSI Length")',
        ),
        (
            'input(28, "Number of candles", type=input.integer)',
            'input.int(28, "Number of candles")',
        ),
        (
            'input(30, "RSI Oversold level", type=input.float)',
            'input.float(30, "RSI Oversold level")',
        ),
        (
            'input(85, "RSI Overbought level", type=input.float)',
            'input.float(85, "RSI Overbought level")',
        ),
        (
            'input(title="Enter longs ?", type = input.bool, defval=true)',
            'input.bool(title="Enter longs ?", defval=true)',
        ),
        (
            'input(title="Enter shorts ?", type = input.bool, defval=true)',
            'input.bool(title="Enter shorts ?", defval=true)',
        ),
        (
            'input(title="Use Laguerre on RSI ?", type=input.bool, defval=false)',
            'input.bool(title="Use Laguerre on RSI ?", defval=false)',
        ),
        (
            "rsiV = security(syminfo.tickerid, reso, rsi(vwap(close), length))",
            "rsiV = request.security(syminfo.tickerid, reso, ta.rsi(ta.vwap(close), length))",
        ),
        (
            "color = rsiVWAP > ovrbgt ? color.red : na, transp = 30",
            "color = rsiVWAP > ovrbgt ? color.new(color.red, 30) : na",
        ),
        (
            "color = rsiVWAP < ovrsld ? color.green : na, transp = 30",
            "color = rsiVWAP < ovrsld ? color.new(color.green, 30) : na",
        ),
        ('strategy.entry("Short", false,', 'strategy.entry("Short", strategy.short,'),
        (
            "timebear and crossunder(rsiVWAP, ovrbgt)",
            "timebear and ta.crossunder(rsiVWAP, ovrbgt)",
        ),
        (
            "timebear and crossunder(rsiVWAP, ovrsld)[lateleave] or crossover(rsiVWAP, ovrsld)",
            "timebear and ta.crossunder(rsiVWAP, ovrsld)[lateleave] or ta.crossover(rsiVWAP, ovrsld)",
        ),
    )
    for old, new in replacements:
        assert code.count(old) == 1, old
        code = code.replace(old, new)
    return code


OBSERVER = """
plot(ta.vwap(close), title="Observed chart VWAP")
plot(ta.rsi(ta.vwap(close), length), title="Observed chart RSI")
plot(ta.crossunder(rsiVWAP, ovrbgt) ? 1 : 0, title="Observed entry cross")
plot((timebear and ta.crossunder(rsiVWAP, ovrsld)[lateleave] or ta.crossover(rsiVWAP, ovrsld)) ? 1 : 0, title="Observed exit cross")
"""


def load_case(row, stop=None):
    raw = (ROOT / row["file"]).read_bytes()
    assert sha256(raw) == row["sha256"]
    bars = json.loads(raw)
    assert len(bars) == row["bars"]
    keys = ("time", "open", "high", "low", "close", "volume")
    return [dict(zip(keys, b, strict=True)) for b in bars[:stop]]


def engine_options(market):
    return {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "1",
        "request_bars": {
            "$chart": {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
        },
    }


def signal_oracle(feed):
    previous_day = None
    previous_vwap = None
    traded_volume = notional = 0.0
    up = down = 0.0
    anchors = []
    values = []
    entries = []
    delayed_down = []
    exits = []
    for i, row in enumerate(feed):
        day = row["time"] // DAY
        if day != previous_day:
            previous_day = day
            traded_volume = notional = 0.0
        assert row["volume"] > 0
        traded_volume += row["volume"]
        notional += row["volume"] * row["close"]
        vwap = notional / traded_volume
        anchors.append(vwap)
        if previous_vwap is not None:
            change = vwap - previous_vwap
            gain, loss = max(0.0, change), max(0.0, -change)
            if i <= 20:
                up += gain / 20
                down += loss / 20
            else:
                up = (19 * up + gain) / 20
                down = (19 * down + loss) / 20
        previous_vwap = vwap
        rsi = None
        if i >= 20:
            rsi = 100.0 if down == 0 else 100 - 100 / (1 + up / down)
        previous_rsi = values[-1] if values else None
        values.append(rsi)
        ready = rsi is not None and previous_rsi is not None
        entries.append(bool(ready and rsi < 85 <= previous_rsi))
        delayed_down.append(bool(ready and rsi < 30 <= previous_rsi))
        exits.append(
            (i >= 28 and delayed_down[i - 28])
            or bool(ready and rsi > 30 >= previous_rsi)
        )
    return anchors, values, entries, exits


def near(a, b):
    if a is None or b is None:
        assert a is b, (a, b)
    else:
        assert math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8), (a, b)


def verify_series(base, observed, oracle, market):
    vwap, rsi, entries, exits = oracle
    native_rsi = base["plots"][0]["values"]
    actual_vwap, local_rsi, actual_entries, actual_exits = [
        plot["values"] for plot in observed["plots"][-4:]
    ]
    for i, (a, b, c, d) in enumerate(zip(vwap, rsi, entries, exits, strict=True)):
        try:
            near(actual_vwap[i], a)
            near(native_rsi[i], b)
            near(local_rsi[i], b)
            assert actual_entries[i] == int(c) and actual_exits[i] == int(d), (
                actual_entries[i],
                c,
                actual_exits[i],
                d,
            )
        except AssertionError as exception:
            raise AssertionError(
                f"{market} at bar {i} {a=}, {b=}, {c=}, {d=}: {exception}"
            ) from exception


def audit_ledger(broker, feed, entries, exits):
    orders = iter(broker["orders"])
    trades = iter(broker["trades"])
    quantity = 0.0
    pending_order = None
    equity = CAPITAL
    ledger = []
    for i, (bar, should_enter, should_exit) in enumerate(
        zip(feed, entries, exits, strict=True)
    ):
        price = bar["open"]
        time = bar["time"]
        if pending_order:
            order = next(orders)
            assert i == order["barIndex"] and time == order["time"]
            near(price, order["price"])
            if pending_order == "short":
                assert order["id"] == "Short" and order["direction"] == "strategy.short"
                quantity = math.floor(equity * 0.50 / price * 1000 + 1e-10) / 1000
                assert quantity > 0
                entry_time, entry_price = time, price
                near(quantity, order["qty"])
            else:
                assert (
                    order["id"] == "Close entry(s) order Short"
                    and order["direction"] == "strategy.close"
                )
                trade = next(trades)
                assert (
                    trade["id"] == "Short"
                    and trade["entryTime"] == entry_time
                    and trade["exitTime"] == time
                )
                near(trade["entryPrice"], entry_price)
                near(trade["exitPrice"], price)
                near(order["qty"], quantity)
                near(trade["qty"], -quantity)
                gross = quantity * (entry_price - price)
                near(trade["profit"], gross)
                overlay = FEE_OVERLAY * quantity * (price + entry_price)
                ledger.append(
                    {
                        **trade,
                        "fee_sensitivity": overlay,
                        "after_fee_sensitivity": gross - overlay,
                    }
                )
                equity += gross
                quantity = 0.0
        if quantity:
            pending_order = "close" if should_exit else None
        else:
            pending_order = "short" if should_enter else None
    assert next(orders, None) is None and next(trades, None) is None
    unsettled = None
    if quantity:
        unsettled = {
            "entryTime": entry_time,
            "entryPrice": entry_price,
            "qty": -quantity,
        }
        equity += quantity * (entry_price - feed[-1]["close"])
    last = broker["position"][-1] if broker["position"] else {"size": 0}
    near(last["size"], -quantity)
    near(broker["equity"][-1]["equity"], equity)
    return ledger, unsettled


def probe():
    source = migrate()
    row = json.loads((ROOT / "2864-inputs.json").read_bytes())["feeds"][0]
    feed = load_case(row, 2880)
    options = engine_options(row["market"])
    base = pine_compat.run_script(source, feed, **options)
    observed = pine_compat.run_script(source + OBSERVER, feed, **options)
    assert observed["strategy"] == base["strategy"]
    oracle = signal_oracle(feed)
    verify_series(base, observed, oracle, row["market"])
    audit_ledger(base["strategy"], feed, *oracle[2:])
    report = {
        "base": base,
        "observed": observed["plots"][-4:],
        "migrated_sha256": sha256(source.encode()),
    }
    (ROOT / "2864-probe.json").write_text(json.dumps(report, indent=2), encoding="utf8")


def replay():
    engine_path = ROOT / "priced-runtime/pine_compat/pine_compat.pyd"
    engine_hash = sha256(engine_path.read_bytes())
    assert (
        engine_hash
        == "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
    )
    source = migrate()
    input_file = ROOT / "2864-inputs.json"
    manifest = json.loads(input_file.read_bytes())
    compiled = pine_compat.compile_script(source)
    observed_compiled = pine_compat.compile_script(source + OBSERVER)
    runs = []
    for reference in manifest["feeds"]:
        market = reference["market"]
        feed = load_case(reference)
        assert [bar["time"] for bar in feed] == list(
            range(reference["start"], reference["stop"], 60_000)
        )
        options = engine_options(market)
        base = compiled.run(feed, **options)
        observed = observed_compiled.run(feed, **options)
        assert not base["diagnostics"] and not base["strategy"]["diagnostics"]
        assert base["strategy"] == observed["strategy"] and not observed["diagnostics"]
        oracle = signal_oracle(feed)
        verify_series(base, observed, oracle, market)
        ledger, unsettled = audit_ledger(base["strategy"], feed, *oracle[2:])
        runs.append(
            {
                **reference,
                "fills": len(base["strategy"]["orders"]),
                "entry_signals": sum(oracle[2]),
                "exit_signals": sum(oracle[3]),
                "closed": len(ledger),
                "ending_position": unsettled,
                "ledger": ledger,
            }
        )
        (ROOT / "2864-replay-progress.json").write_text(
            json.dumps(runs, indent=2), encoding="utf8"
        )
    report = {
        "engine_sha256": engine_hash,
        "migrated_sha256": sha256(source.encode()),
        "inputs": manifest,
        "runs": runs,
    }
    (ROOT / "2864-replay.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["probe"]:
            probe()
        else:
            replay()
    except Exception:
        import traceback

        (ROOT / "2864-error.txt").write_text(traceback.format_exc(), encoding="utf8")
        raise
