"""Reconcile the exact #4307 Pine probe and a full-window KDJ replay."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round32_trailing_offset import sma

SOURCE = "29ff9d35d78c1959dd227e7f77bfebde4e38582dcfdc0a333b48f922f423fcc2"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000


def recurrence(values, seed, alpha):
    pending = []
    output = []
    state = None
    for value in values:
        if value is not None:
            if state is None:
                pending.append(value)
                if len(pending) == seed:
                    state = math.fsum(pending) / seed
            else:
                state = alpha * value + (1 - alpha) * state
        output.append(state)
    return output


def frame_values(bars, per_day, require_complete):
    ranges = []
    for i, (_, _, hi, lo, close, _) in enumerate(bars):
        previous = bars[i - 1][4] if i else close
        ranges.append(max(hi - lo, abs(hi - previous), abs(lo - previous)))
    atr = recurrence(ranges, 14, 1 / 14)
    last = list(range(per_day - 1, len(bars), per_day))
    sampled = [bars[i] for i in last]
    volatility = [atr[i] / bars[i][4] for i in last]
    lengths = [3 if v > .03 else 14 if v > .002 else 15 for v in volatility]
    rsv = []
    for i, length in enumerate(lengths):
        sample = sampled[max(0, i - length + 1):i + 1]
        if require_complete and len(sample) != length:
            rsv.append(None)
            continue
        hi, lo = max(r[2] for r in sample), min(r[3] for r in sample)
        rsv.append(100 * (sampled[i][4] - lo) / (hi - lo) if hi > lo else None)
    k = sma(rsv, 3)
    d = sma(k, 3)
    j = [3 * a - 2 * b if b is not None else None for a, b in zip(k, d, strict=True)]
    return lengths, k, d, j


def projected_values(frames, require_complete=True, seed=5):
    widths = (1, 5, 15)
    legs = [frame_values(frames[str(interval)], 1440 // interval, require_complete)
            for interval in widths]
    weights = (.5, .33, 1 - (.5 + .33))
    combined = [
        [math.fsum(w * p for w, p in zip(weights, terms, strict=True))
         if None not in terms else None for terms in zip(*(leg[i] for leg in legs), strict=True)]
        for i in (1, 2, 3)
    ]
    total = [math.fsum(row) / 3 if None not in row else None for row in zip(*combined, strict=True)]
    smooth = dict(zip(("k", "d", "j", "total"),
                      (recurrence(series, seed, 1 / 3) for series in (*combined, total)), strict=True))
    return {**smooth, **{f"len{width}": leg[0] for width, leg in zip(widths, legs, strict=True)}}


def entry_gates(data):
    trend = sma(data["total"], 40)
    buy, sell = [], []
    for i, (k, d, j, total, average) in enumerate(zip(data["k"], data["d"], data["j"],
                                                    data["total"], trend, strict=True)):
        if i == 0 or None in (k, d, j, total, data["k"][i - 1], data["d"][i - 1]):
            continue
        previous_k, previous_d = data["k"][i - 1], data["d"][i - 1]
        up = average is not None and average > 60
        down = average is not None and average < 40
        buy_level = 40 if up else 15 if down else 25
        sell_level = 85 if up else 60 if down else 75
        crossed_up = j < buy_level and k > d and previous_k <= previous_d
        crossed_down = j > sell_level and k < d and previous_k >= previous_d
        anticipate_buy = k > previous_k and d < previous_d and abs(k - d) < 5
        anticipate_sell = k < previous_k and d > previous_d and abs(k - d) < 5
        if (crossed_up or anticipate_buy) and total < 22:
            buy.append(i)
        if (crossed_down or anticipate_sell) and total > 78:
            sell.append(i)
    return buy, sell


def audit(market, frames, replay):
    expected_sizes = {"D":24,"1":34_560,"5":6_912,"15":2_304}
    assert {key: len(rows) for key,rows in frames.items()} == expected_sizes
    source = replay["original"]
    assert source == replay["cross_diagnostics_control"] == replay["stop_only_diagnostic"]
    broker, plots = source["broker"], source["plots"]
    assert not source["diagnostics"] and not broker["diagnostics"]
    assert not broker["orders"] and not broker["trades"] and not broker["position"]
    assert len(broker["equity"]) == 24
    assert all(row["cash"] == row["equity"] == CAPITAL and row["marketValue"] == row["netProfit"] == 0
               for row in broker["equity"])
    calculated = projected_values(frames)
    for name, values in calculated.items():
        assert all(a == b or None not in (a,b) and math.isclose(a,b,abs_tol=1e-9)
                   for a,b in zip(plots["scope " + name], values, strict=True)), name
    buy,sell = entry_gates(calculated)
    assert not buy and not sell and plots["scope long"] == plots["scope short"] == [0] * 24
    assert entry_gates(projected_values(frames, seed=1)) == ([],[])
    partial = entry_gates(projected_values(frames, require_complete=False))
    assert partial == (([],[23]) if market=="BTCUSDT" else ([14],[]))
    return {"market":market,"source_bars":expected_sizes,
            "finite_composite":[v for v in calculated["total"] if v is not None],
            "native_and_first_value_ema_entries":0,
            "incomplete_window_diagnostic":{"long_bars":partial[0],"short_bars":partial[1]},
            "literal_order_count":len(broker["orders"])}


def main(work,out):
    assert sha256(work/"source-4307.md") == SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    feed, raw = work/"4307-feed.json", work/"4307-native.json"
    data = read(feed)
    assert len(data["receipts"]) == 4
    native = read(raw)
    cases = [audit(m, f, native[m]) for m,f in data["market_data"].items()]
    isolation = read(work/"round3-isolation-python.json")
    assert set(isolation) == {"file_error","network_error"}
    assert all(v[0] == "PermissionError" for v in isolation.values())
    attrs={"id":4307,"group":"FMZ Pine v5 · exact saved interval",
           "exit":"Archived long/short gates and named stop calls",
           "period":"Binance USD-M · 2025-01-01 to 2025-01-25 UTC exclusive",
           "interval":"1d","archive_interval":"1d","currency":"USDT"}
    rows=[{**attrs,"market":m,**ledger_metrics([],CAPITAL*(2 if " + " in m else 1),0)}
          for m in ("BTCUSDT","ETHUSDT","BTCUSDT + ETHUSDT")]
    write(out, {"schema":"FMZ #4307 exact v5 KDJ and authenticated lower-timeframe replay",
                "source_url":"https://www.fmz.com/strategy/489320",
                "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
                "source_sha256":SOURCE,"engine_sha256":ENGINE,"native_sha256":sha256(raw),
                "input_sha256":sha256(feed),"market_receipts":data["receipts"],
                "isolation":isolation,"cases":cases,
                "coverage":[[4307,"Tested · archived full-window KDJ, zero signals",
                             "Exact v5 source matches independent KDJ, ATR and full-history extrema on 24 true daily bars with 34,560 authenticated 1m rows per market. Explicit 5m/15m child data and two EMA seeds agree on no entries. Stop fields remain unexercised."]],
                "results":rows})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
