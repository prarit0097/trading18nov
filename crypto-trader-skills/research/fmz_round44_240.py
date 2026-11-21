"""Test the archived Demark rule with the catalogue's valid chart-timeframe setting."""

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS

SOURCE = "41d4aa2aed7a2db03c6e6c5d4b05a4298c134b6816613326cc0855dabd31bf9a"
RELATED = "ba63a53fa83d78956403e791fabd57983db18aa7266575c40391d88919422b42"
RELATED_URL = "https://raw.githubusercontent.com/fmzquant/strategies/7853bb2bf262c4567ac238d3552d97f0e50cb801/Demark-Reversal-Points-CC.md"
BEGIN, END = map(date_ms, ("2022-02-06", "2022-05-06"))
HOUR = 3_600_000
CAPITAL = 1_000_000
FEE = 0.00075
BAD_RESOLUTION = "res = input.int(title='Resolution', defval='18000')"
GOOD_RESOLUTION = "res = input.timeframe(title='Resolution', defval='')"
OBSERVE = '\nplot(src, "Audit lagged close")\nplot(drp, "Audit reversal state")\n'


def pine_document(path):
    fence = chr(96) * 3
    (body,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        path.read_text(encoding="utf-8"),
    )
    script, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert count == 1
    return script


def scripts(document, related):
    assert sha256(document) == SOURCE and sha256(related) == RELATED
    source, alternate = pine_document(document), pine_document(related)
    assert source.count(BAD_RESOLUTION) == 1 and alternate.count(GOOD_RESOLUTION) == 1

    def core(text):
        return text[text.index("length = input.int") : text.index("sig = drp")].strip()

    assert core(source) == core(alternate)
    original = source.replace(
        "//@version=5", '//@version=5\nstrategy("Demark reversal point benchmark")', 1
    )
    projected = original.replace(BAD_RESOLUTION, GOOD_RESOLUTION) + OBSERVE
    offset_line = "src = request.security(syminfo.tickerid, res, inp[0])[1]"
    assert projected.count(offset_line) == 1
    return original, projected, projected.replace(offset_line, "src = inp[1]")


def chart(folder, market, receipts):
    feeds = {}
    for timeframe, step in (("15m", HOUR // 4), ("1h", HOUR)):
        path = folder / f"{market}-{timeframe}.json"
        rows = [
            (t, o, h, l, c, v) for t, o, c, h, l, v in json.loads(path.read_bytes())
        ]
        assert all(
            BEGIN <= t < END
            and t % step == 0
            and 0 < l <= min(o, c) <= max(o, c) <= h
            and v > 0
            for t, o, h, l, c, v in rows
        )
        assert list(dict.fromkeys(b[0] for b in rows)) == sorted(b[0] for b in rows)
        values = {r[0] for r in rows}
        assert len(values) == len(rows)
        gaps = sorted(set(range(BEGIN, END, step)) - values)
        if timeframe == "15m":
            day = date_ms("2022-04-19")
            assert gaps == list(
                range(day + 11 * HOUR + HOUR // 2, day + 12 * HOUR + HOUR // 2, step)
            )
        else:
            assert not gaps
        feeds[timeframe] = rows
        url = (
            f"https://api-pub.bitfinex.com/v2/candles/trade:{timeframe}:t{market}/hist"
            f"?start={BEGIN}&end={END - 1}&limit=10000&sort=1"
        )
        receipts.append(
            {
                "url": url,
                "sha256": sha256(path),
                "rows": len(rows),
                "missing_starts": gaps,
            }
        )
    buckets = defaultdict(list)
    for sub in feeds["15m"]:
        buckets[sub[0] // HOUR * HOUR].append(sub)
    for bar in feeds["1h"]:
        children = buckets[bar[0]]
        assert aggregate(children, len(children))[0][1:5] == bar[1:5]
    return aggregate(feeds["1h"], 2), {t: rows[0] for t, rows in buckets.items()}


def witnesses(bars):
    lag = [None] + [p[4] for p in bars[:-1]]
    padded = [0] * 12 + [p or 0 for p in lag]
    state = []
    for i in range(len(bars)):
        here = i + 12
        delta = [padded[here - j] - padded[here - j - 4] for j in range(9)]
        state.append(
            1 if all(d < 0 for d in delta) else -1 if all(d > 0 for d in delta) else 0
        )
    return lag, state


def settle(bars, state, receipts, openings):
    held = previous = target = 0
    entry = stamp = None
    cash = CAPITAL
    orders, trades = [], []
    for i, (time, price, _, _, close, _) in enumerate(bars):
        if target and target != held:
            assert openings[time][:2] == (time, price)
            if held:
                fee = (entry + price) * FEE
                gross = held * (price - entry)
                trades.append(
                    {
                        "dir": held,
                        "qty": 1,
                        "entryTime": stamp,
                        "exitTime": time,
                        "entryPrice": entry,
                        "exitPrice": price,
                        "commission": fee,
                        "profit": gross - fee,
                    }
                )
            label = "Long" if target == 1 else "Short"
            orders.append(
                (
                    f"Enter {label}",
                    time,
                    price,
                    abs(target - held),
                    f"strategy.{label.lower()}",
                )
            )
            cash -= (target - held) * price
            held, entry, stamp = target, price, time
        now = state[i]
        target = now if now != 0 and now != previous else 0
        previous = now
        native = receipts["equity"][i]
        assert math.isclose(cash, native["cash"], rel_tol=0, abs_tol=1e-7)
        assert math.isclose(
            cash + held * close, native["equity"], rel_tol=0, abs_tol=1e-7
        )
    columns = ("id", "time", "price", "qty", "direction")
    native_orders = [tuple(x[k] for k in columns) for x in receipts["orders"]]
    for a, b in zip(orders, native_orders, strict=True):
        assert a[:2] == b[:2] and a[3:] == b[3:], (a, b)
        assert math.isclose(a[2], b[2], rel_tol=0, abs_tol=1e-9), (a, b)
    for a, b in zip(trades, receipts["trades"], strict=True):
        assert a["dir"] == b["qty"]
        assert all(a[k] == b[k] for k in ("entryTime", "exitTime"))
        assert all(
            math.isclose(a[k], b[k], rel_tol=0, abs_tol=1e-9)
            for k in ("entryPrice", "exitPrice")
        )
        assert math.isclose(a["profit"] + a["commission"], b["profit"], abs_tol=1e-8)
    assert held == receipts["position"][-1]["size"]
    return (
        orders,
        trades,
        {
            "side": held,
            "entry": entry,
            "mark": close,
            "unrealized_gross": held * (close - entry),
            "modeled_opening_fee": entry * FEE,
        },
    )


def check(engine, programs, market, bars, openings):
    encoded = [dict(zip(FIELDS, row, strict=True)) for row in bars]
    params = {
        "chart_timeframe": "120",
        "chart_symbol": f"BITFINEX:{market}",
        "request_bars": {
            "$chart": {
                "minMove": 1,
                "priceScale": 100_000_000,
                "minContract": ".00000001",
                "quantityStep": ".00000001",
                "currency": "USD",
            }
        },
    }
    try:
        engine.run_script(programs[0], encoded, **params)
    except ValueError as error:
        failure = str(error)
        assert "E_CALL_ARG_TYPE" in failure
    else:
        raise AssertionError("The malformed saved resolution unexpectedly compiled")
    original, control = [engine.run_script(p, encoded, **params) for p in programs[1:]]
    assert not original["diagnostics"] and not original["strategy"]["diagnostics"]
    assert original["strategy"] == control["strategy"]
    lag, state = witnesses(bars)
    for version in (original, control):
        plots = {p.get("title"): p.get("values") for p in version["plots"]}
        assert (
            plots["Audit lagged close"] == lag
            and plots["Audit reversal state"] == state
        )
    orders, trades, terminal = settle(bars, state, original["strategy"], openings)
    assert trades and terminal["side"]
    return {
        "market": market,
        "verified_2h_bars": len(bars),
        "orders": orders,
        "closed": trades,
        "terminal": terminal,
        "invalid_saved_resolution_error": failure.splitlines()[0],
    }


def main(document, related, data, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    programs, receipts, cases = scripts(document, related), [], []
    for market in ("BTCUSD", "ETHUSD"):
        bars, openings = chart(data, market, receipts)
        cases.append(check(pine_compat, programs, market, bars, openings))
    info = {
        "id": 240,
        "group": "FMZ Demark · documented chart-timeframe variant",
        "period": "2022-02-06 to 2022-05-06 UTC exclusive",
        "currency": "USD",
        "interval": "2h",
        "archive_interval": "2h",
        "pine_source_version": "5",
        "order_family": "Fixed-unit reversal at next opening print",
        "exit": "Opposite Demark reversal",
    }
    results = []
    for selected in ([cases[0]], [cases[1]], cases):
        results.append(
            {
                **info,
                "market": " + ".join(c["market"] for c in selected),
                **ledger_metrics(
                    [t for c in selected for t in c["closed"]],
                    CAPITAL * len(selected),
                    len(selected),
                ),
            }
        )
    write(
        output,
        {
            "schema": "FMZ #240 same-venue test of the published valid timeframe variant",
            "source_url": "https://www.fmz.com/strategy/361719",
            "source_sha256": SOURCE,
            "related_source": {"url": RELATED_URL, "sha256": RELATED},
            "engine_sha256": ENGINE_SHA,
            "bitfinex_archives": receipts,
            "cases": cases,
            "results": results,
            "notes": "The original saved input puts a quoted 18000 in an integer argument and uses an out-of-range minute resolution. The related FMZ catalogue version has the identical Demark recurrence and publishes a valid chart-timeframe input. The tested variant uses that published input and preserves the archived one-chart-bar lag and both order rules. The archive's strategy entries are supported by supplying an explicit strategy declaration. The venue, window, instrument and chart interval match the archived BTC settings, and ETH is a matched cross-market test. All 1h OHLC values match official 15m observations, including hours with partly absent children. No modeled fill uses a missing first 15m observation. One base unit per position, a 0.075% modeled fee per side, and no margin financing or liquidity cost.",
            "references": [
                "https://www.fmz.com/doc/9293#request.security",
                "https://docs.bitfinex.com/reference/rest-public-candles",
            ],
            "coverage": [
                [
                    240,
                    "Tested · published valid timeframe variant; 18000 archive invalid",
                    "Same Demark recurrence, original Bitfinex BTC and date window and matched ETH. Published chart-timeframe alternative preserves the prior-chart-bar confirmation and source market reversals. Saved 18000 never qualifies for performance.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
