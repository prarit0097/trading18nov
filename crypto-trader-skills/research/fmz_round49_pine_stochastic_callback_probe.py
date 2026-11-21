"""Replay the archived Stochastic/SMA strategy at causal observed minute ticks."""

import json
import re
import sys
import traceback
from hashlib import sha256
from importlib import import_module
from itertools import batched
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
data = json.loads((w / "round47-3689-feeds.json").read_bytes())
src = (w / "round47-3689-active.pine").read_text(encoding="utf8")
source = src + "".join(
    f'\nplot({expr}, "{name}")'
    for name, expr in {
        "LongGate": "longcondition?1:0",
        "ShortGate": "shortcondition?1:0",
        "K": "k",
        "D": "d",
        "SMA high": "high_line",
        "SMA low": "low_line",
        "Open PnL": "strategy.openprofit",
        "Position": "strategy.position_size",
        "Basis": "strategy.position_avg_price",
        "Equity": "strategy.equity",
    }.items()
)
fields = ("time", "open", "high", "low", "close", "volume")
guard, n = re.subn(
    r"(?m)^([ \t]+)(strategy\.exit\([^\n]*\bstop = stoploss[^\n]*)$",
    lambda m: (
        m[1]
        + (
            "if not na(stoploss) or not na(takeprofit)\n"
            if "profit = takeprofit" in m[2]
            else "if not na(stoploss)\n"
        )
        + m[1]
        + "    "
        + m[2]
    ),
    source,
)
assert n == 4, n
feed = {}
for tag, markets in data["scopes"].items():
    for coin, tape in markets.items():
        key = tag + "/" + coin
        chart = [dict(zip(fields, x)) for x in tape["15m"]]
        sym = "BINANCE:" + coin + "USDT"
        opts = {
            "$chart": {
                "minMove": 1,
                "priceScale": 10 if coin == "BTC" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "minContract": "0.001",
                "quantityStep": "0.001",
            },
            "$currencyRates": {
                "schemaVersion": 1,
                "pairs": [{"from": "USDT", "to": "USD", "rates": data["fx"]}],
            },
        }
        try:
            native = pine.run_script(
                source, chart, chart_symbol=sym, chart_timeframe="15", request_bars=opts
            )
            feed[key] = {
                "normal": native["strategy"],
                "normal_diagnostics": native["diagnostics"],
                "normal_gate": {
                    x["title"]: x["values"]
                    for x in native["plots"]
                    if x.get("title")
                    in ("LongGate", "ShortGate", "K", "D", "SMA high", "SMA low")
                },
            }

            gated = pine.run_script(
                guard, chart, chart_symbol=sym, chart_timeframe="15", request_bars=opts
            )
            assert not gated["diagnostics"] and not gated["strategy"]["diagnostics"]
            assert all(
                d["code"] == "E_STRATEGY_EXIT_PRICE"
                for d in native["strategy"]["diagnostics"]
            )
            assert native["strategy"]["orders"] == gated["strategy"]["orders"]
            assert native["strategy"]["trades"] == gated["strategy"]["trades"]
            feed[key]["guarded_source_sha256"] = sha256(guard.encode()).hexdigest()
            feed[key]["literal_source_sha256"] = sha256(source.encode()).hexdigest()
            feed[key]["literal_non_finite_exit_diagnostics"] = len(
                native["strategy"]["diagnostics"]
            )
            program = pine.compile_script(guard)
            for base in ("5m", "1m"):
                step = int(base[:-1]) * 60_000
                count = 15 // int(base[:-1])
                session = program.realtime_session(
                    chart_timeframe="15", chart_symbol=sym, request_bars=opts
                )
                session.seed_state(
                    chart[:1], execution_times=[chart[0]["time"] + 900_000 - 1]
                )
                journal = {"orders": [], "trades": []}
                differences = []

                def commit(delta, t, q, cycle, tag, journal, differences):
                    assert not delta["diagnostics"], delta["diagnostics"]
                    answer = delta["strategy"]
                    assert not answer["diagnostics"], answer["diagnostics"]
                    for label, log in journal.items():
                        part = answer.get(label)
                        if not part:
                            continue
                        first = part["start"]
                        stable = len(log) - first
                        assert 0 <= stable <= len(part["items"]), (
                            first,
                            len(log),
                            part["items"],
                        )
                        assert [x[3] for x in log[first:]] == part["items"][:stable]
                        for event in part["items"][stable:]:
                            assert (
                                event[
                                    "barIndex" if label == "orders" else "exitBarIndex"
                                ]
                                == cycle
                            )
                            px = event["price" if label == "orders" else "exitPrice"]
                            if abs(px - q) > 1e-8:
                                differences.append([t, q, px, tag])
                            log.append([t, tag, q, event])

                for index, (parent, group) in enumerate(
                    zip(
                        chart[1:],
                        list(batched(tape[base], count, strict=True))[1:],
                        strict=True,
                    ),
                    1,
                ):
                    origin = parent["open"]
                    high = low = origin
                    vol = 0.0
                    for i, (ts, o, h, l, c, v) in enumerate(group):
                        frame = {
                            "time": parent["time"],
                            "open": origin,
                            "high": max(high, o),
                            "low": min(low, o),
                            "close": o,
                            "volume": vol,
                        }
                        delta = session.apply_forming(
                            frame, execution_time=ts, opening_update=(i == 0)
                        )
                        commit(
                            delta, ts, o, index, base + " open", journal, differences
                        )
                        high = max(high, h)
                        low = min(low, l)
                        vol += v
                        final = i == count - 1
                        frame = {
                            "time": parent["time"],
                            "open": origin,
                            "high": high,
                            "low": low,
                            "close": c,
                            "volume": vol,
                        }
                        if final:
                            assert all(frame[f] == parent[f] for f in fields[:-1])
                        method = (
                            session.apply_confirmed if final else session.apply_forming
                        )
                        delta = method(
                            frame, execution_time=ts + step - 1, opening_update=False
                        )
                        commit(
                            delta,
                            ts + step - 1,
                            c,
                            index,
                            base + " close",
                            journal,
                            differences,
                        )
                end = session.confirmed_result()
                assert [a[3] for a in journal["trades"]] == end["strategy"]["trades"]
                assert [a[3] for a in journal["orders"]] == end["strategy"]["orders"]
                assert not differences, differences
                feed[key][base] = {
                    "event": journal,
                    "price_disagreements": differences,
                    "strategy": end["strategy"],
                    "gates": {
                        x["title"]: x["values"]
                        for x in end["plots"]
                        if x.get("title")
                        in ("LongGate", "ShortGate", "K", "D", "SMA high", "SMA low")
                    },
                }
        except (
            AssertionError,
            TypeError,
            ValueError,
            RuntimeError,
            AttributeError,
            KeyError,
        ):
            feed.setdefault(key, {})["error"] = traceback.format_exc()
(w / "round47-3689-guard.json").write_text(
    json.dumps(feed, default=str, separators=(",", ":")), encoding="utf8"
)
