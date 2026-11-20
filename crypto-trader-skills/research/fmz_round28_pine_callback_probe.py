import json
import re
import sys
import traceback
from datetime import UTC, datetime
from importlib import import_module
from itertools import batched
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine_compat = import_module("pine_compat")
source = re.sub(
    r"(?ms)^/\*backtest\n.*?^\*/\n*",
    "",
    (w / "round28-bb-source.pine").read_text(encoding="utf8"),
)
plots = {
    "New close": "newClose",
    "ATR": "atr",
    "Long stop": "longStop",
    "Short stop": "shortStop",
    "Direction": "dir",
    "Year high": "yearlyHighCondition?1:0",
    "Year low": "yearlyLowCondition?1:0",
    "Buy": "buyCondition?1:0",
    "Sell": "sellCondition?1:0",
    "Position": "strategy.position_size",
}
code = source + "\n".join(f'\nplot({v}, "{k}")' for k, v in plots.items())
cases = json.loads((w / "round28-bb-feeds.json").read_bytes())
years = json.loads((w / "round28-bb-years.json").read_bytes())
result = []

hours = json.loads((w / "round28-bb-hours.json").read_bytes())


def commit(tape, delta, tick, price, phase, index):
    assert not delta["diagnostics"]
    broker_delta = delta["strategy"]
    assert not broker_delta["diagnostics"]
    for tag, journal in tape.items():
        changed = broker_delta.get(tag)
        if not changed:
            continue
        first = changed["start"]
        stable = len(journal) - first
        assert 0 <= stable <= len(changed["items"])
        assert [v["row"] for v in journal[first:]] == changed["items"][:stable], (
            tag,
            changed,
            journal[first:],
            tick,
            price,
            phase,
            index,
        )
        for item in changed["items"][stable:]:
            assert item["barIndex" if tag == "orders" else "exitBarIndex"] == index
            actual = item["price" if tag == "orders" else "exitPrice"]
            assert actual == price, (tag, actual, price, item, tick, phase)
            journal.append({"event_time": tick, "phase": phase, "row": item})


try:
    program = pine_compat.compile_script(code)
    for period, markets in cases.items():
        for m, chart in markets.items():
            if sys.argv[1:] and m not in sys.argv[1:]:
                continue
            fields = ("time", "open", "high", "low", "close", "volume")
            candles = [dict(zip(fields, r, strict=True)) for r in chart]
            symbol = f"BINANCE:{m}"
            start_year = datetime.fromtimestamp(chart[0][0] / 1000, UTC).year
            annual = [
                dict(zip(fields, a, strict=True))
                for a in years[m]
                if datetime.fromtimestamp(a[0] / 1000, UTC).year < start_year
            ]
            market = {
                "minMove": 1,
                "priceScale": 10 if m == "BTCUSDT" else 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
            session = program.realtime_session(
                chart_timeframe="1D",
                chart_symbol=symbol,
                request_bars={"$chart": market, symbol + ":12M": annual},
            )
            session.seed_state(
                candles[:1], execution_times=[candles[0]["time"] + 86_399_999]
            )
            tape = {"orders": [], "trades": []}

            bins = list(batched(hours[period][m], 24, strict=True))
            for i, (bar, day_hours) in enumerate(
                zip(candles[1:], bins[1:], strict=True), 1
            ):
                chart_t = bar["time"]
                seen_high = seen_low = bar["open"]
                seen_vol = 0
                for j, (t, o, h, l, c, v) in enumerate(day_hours):
                    opening = {
                        "time": chart_t,
                        "open": bar["open"],
                        "high": max(seen_high, o),
                        "low": min(seen_low, o),
                        "close": o,
                        "volume": seen_vol,
                    }
                    tick = session.apply_forming(
                        opening, execution_time=t, opening_update=(j == 0)
                    )
                    commit(tape, tick, t, o, "hour open", i)
                    seen_high = max(seen_high, h)
                    seen_low = min(seen_low, l)
                    seen_vol += v
                    final = j == 23
                    snapshot = {
                        "time": chart_t,
                        "open": bar["open"],
                        "high": seen_high,
                        "low": seen_low,
                        "close": c,
                        "volume": seen_vol,
                    }
                    if final:
                        assert all(snapshot[key] == bar[key] for key in fields[:-1])
                    handler = (
                        session.apply_confirmed if final else session.apply_forming
                    )
                    day_tick = handler(
                        snapshot, execution_time=t + 3_599_999, opening_update=False
                    )
                    commit(tape, day_tick, t + 3_599_999, c, "hour close", i)
            r = session.confirmed_result()
            for tag, journal in tape.items():
                assert [v["row"] for v in journal] == r["strategy"][tag]
            result.append(
                {
                    "period": period,
                    "market": m,
                    "events": tape,
                    "strategy": r["strategy"],
                    "observations": {
                        p["title"]: p["values"]
                        for p in r["plots"]
                        if p.get("title") in plots
                    },
                }
            )
except Exception:
    (
        w / ("round28-bb-hour-error-" + ("-".join(sys.argv[1:]) or "all") + ".txt")
    ).write_text(traceback.format_exc(), encoding="utf8")
    raise
(
    w / ("round28-bb-hour-results-" + ("-".join(sys.argv[1:]) or "all") + ".json")
).write_text(json.dumps(result, separators=(",", ":")), encoding="utf8", newline="\n")
