"""Replay archived FMZ JavaScript CTA and directional recipes on linear perpetuals."""

import argparse
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, NOTIONAL, stamp, summarize
from research.fmz_mylanguage_round3 import bars, ema, inputs
from research.fmz_mylanguage_round5 import Book
from research.fmz_native_round3 import WINDOWS
from research.fmz_native_round5 import BASE, HERE, assert_source
from research.fmz_native_round4 import sha

SPECS = {
    1099: (15, {}, "Correct Length, close and positLon field names in the archived CTA. Keep its executed comparisons with the 20-bar Bollinger midpoint."),
    1133: (15, {"Amount": 100}, "Replace inverse contracts with a 1,000 USDT linear lot and use the archived 30-bar SMA reversal after each completed bar."),
    2624: (60, {"Diff": 40, "Length": 100, "AvgLength": 10, "Name": "rb1810"},
           "Preserve the CTA callback's strict CCI crossings. Substitute BTC/ETH for the Chinese rebar contract and use a 1,000 USDT linear lot."),
    4684: (60, {"ema1Period": 13, "ema2Period": 15, "amount": .1, "profitTarget": 20, "ct": "swap", "okexSimulate": False},
           "Retain matched dual-EMA turning points, 0.1 base units and a 20 USDT price-change profit trigger. Evaluate exits at confirmed hourly closes."),
    5678: (60, {"maLen": 100, "kd1": 50, "kd2": 15},
           "Replay the Chinese rapeseed-meal CTA on BTC/ETH with published KDJ recurrence and the original two-digit string comparisons."),
}


def kdj(h, l, c, periods, smooth):
    high = h.rolling(periods).max()
    low = l.rolling(periods).min()
    rsv = 100 * (c - low) / (high - low)
    k, d = 50., 50.
    ks, ds = [], []
    for value in rsv:
        if not np.isfinite(value):
            ks.append("")
            ds.append("")
            continue
        k = (value + (smooth - 1) * k) / smooth
        d = (k + (smooth - 1) * d) / smooth
        ks.append(str(Decimal.from_float(float(k)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)))
        ds.append(str(Decimal.from_float(float(d)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)))
    return pd.Series(ks, index=c.index), pd.Series(ds, index=c.index)


def features(id_, frame, args):
    f = frame.copy()
    h, l, c = (f[column] for column in ("high", "low", "close"))
    if id_ in (1099, 1133):
        average = c.rolling(20 if id_ == 1099 else 30).mean()
        f["up"], f["down"] = c > average, c < average
        f["close_long"], f["close_short"] = f["down"], f["up"]
    elif id_ == 2624:
        n, avg_n, threshold = args["Length"], args["AvgLength"], args["Diff"]
        typical = (h + l + c) / 3
        deviation = typical.rolling(n).apply(lambda x: np.abs(x - np.mean(x)).mean(), raw=True)
        cci = (typical - typical.rolling(n).mean()) / (.015 * deviation)
        level = cci.rolling(avg_n).mean()
        prior = level.shift()
        f["up"], f["down"] = (prior < threshold) & (level > threshold), (prior > -threshold) & (level < -threshold)
        f["close_long"], f["close_short"] = (prior > threshold) & (level < threshold), (prior < -threshold) & (level > -threshold)
    elif id_ == 4684:
        a, b = (ema(c, args[key]) for key in ("ema1Period", "ema2Period"))
        f["up"] = (a > a.shift()) & (a.shift(2) > a.shift()) & (b > b.shift()) & (b.shift(2) > b.shift())
        f["down"] = (a < a.shift()) & (a.shift(2) < a.shift()) & (b < b.shift()) & (b.shift(2) < b.shift())
        f["close_long"], f["close_short"] = f["down"], f["up"]
    else:
        assert id_ == 5678
        a, b = kdj(h, l, c, args["kd1"], args["kd2"])
        average = c.rolling(100).mean()
        f["up"], f["down"] = (c > average) & (a > b), (c < average) & (a < b)
        f["close_long"], f["close_short"] = a < b, a > b
    return f


def simulate(id_, frame, raw, funding, first, end, args, interval):
    book = Book(funding, 1)
    step = interval * 60
    eligible = frame.loc[pd.Timestamp(first, unit="s", tz="UTC"):pd.Timestamp(end - step - 1, unit="s", tz="UTC")]
    for bar in eligible.itertuples():
        at = int(bar.Index.timestamp()) + step
        quote = raw.loc[pd.Timestamp(at, unit="s", tz="UTC")]
        px = float(quote.open)
        assert px > 0 and quote.volume > 0
        side = book.side
        reverse = id_ in (1133, 4684)
        should_close = (side == 1 and bar.close_long) or (side == -1 and bar.close_short)
        if id_ == 4684 and side and side * (bar.close - book.last) > args["profitTarget"]:
            should_close = True
        if should_close:
            book.close(at, px, book.qty, "exit")
        if not book.side and (not side or reverse):
            direction = 1 if bar.up else -1 if bar.down else 0
            if direction and direction != side:
                book.open(at, px, args.get("amount", NOTIONAL / px), direction, "entry")
    receipt = book.verify(end)
    fills = [(t, gross, gross - fee, gross - fee - cost + carry, carry)
             for _, _, t, _, _, _, gross, fee, cost, carry in book.settled]
    return fills, int(bool(book.side)), receipt


def run(scratch, public_params, output):
    entries = {row["id"]: row for row in read(scratch / "native-expanded" / "native-enriched-candidates.json")}
    archive_audit = {r["id"]: r for r in read(HERE / "fmz-native-round4-coverage.json")["disposition"]}
    pending = {r["id"] for r in read(HERE / "remaining-backtest-round4-coverage.json")["disposition"]
               if not r["status"].startswith("Tested")}
    assert SPECS.keys() <= entries.keys() & pending
    directory = scratch / "nonpine" / "binance"
    manifest = read(directory / "manifest.json")
    market = {coin: inputs(directory, coin + "USDT", manifest) for coin in ("BTC", "ETH")}
    receipts = read(scratch / "round3-native" / "round3-parameter-checks.json") + read(public_params)
    parameters = {row["id"]: row for row in receipts if "args" in row and (row["args"] or row["id"] == 1099)}
    coverage, results, evidence, specs = [], [], [], []
    with ZipFile(scratch / "fmz.zip") as archive:
        for id_, (interval, args, notes) in SPECS.items():
            item = entries[id_]
            assert_source({"item": item}, archive, archive_audit[id_])
            assert args == parameters[id_]["args"]
            specs.append({"id": id_, "source": item["source"], "source_sha256": item["source_sha256"],
                          "code_sha256": sha(item["code"].encode()), "parameters": parameters[id_], "interval": interval})
            frames = {coin: features(id_, bars(value[0], interval), args) for coin, value in market.items()}
            count = opened = 0
            staged = []
            for start, (end, window) in WINDOWS.items():
                runs = {}
                for coin, (raw, funding, _) in market.items():
                    run_fills, active, receipt = simulate(id_, frames[coin], raw, funding, stamp(start), stamp(end), args, interval)
                    evidence.append({"id": id_, "coin": coin, "start": start, **receipt})
                    runs[coin] = run_fills, active
                    count += len(run_fills)
                    opened += active
                btc, ob = runs["BTC"]
                eth, oe = runs["ETH"]
                for label, fills, open_count in (("BTCUSDT", btc, ob), ("ETHUSDT", eth, oe), ("BTCUSDT + ETHUSDT", btc + eth, ob + oe)):
                    result = summarize(("FMZ JavaScript · Closed-bar recipe", item["name"], label + " perp",
                                        "Archived trigger rules"), window, [trade[:4] for trade in fills], open_count)
                    result.update(id=id_, source=item["source"], source_sha256=item["source_sha256"], interval=f"{interval}m",
                                  starting_equity=EQUITY, quote_currency="USDT", adaptation=notes,
                                  market_data="Binance USD-M candles and funding", funding=sum(trade[4] for trade in fills))
                    result["execution"] += result["funding"]
                    staged.append(result)
            if count or opened:
                results.extend(staged)
                coverage.append([id_, "Tested · FMZ JavaScript recipe" + ("" if count else ", no closes"), notes])
            else:
                coverage.append([id_, "FMZ native offline replay pending", "No position matched the documented recipe"])
    write(output, {"baseline": BASE, "source_revision": FMZ_REF, "specs": specs,
                   "market": {coin: value[2] for coin, value in market.items()},
                   "indicator_source": "https://www.fmz.com/bbs-topic/10136",
                   "fill_fields": ["side", "entry", "exit", "entry_price", "exit_price", "size", "gross", "fees", "execution", "funding"],
                   "coverage": coverage, "order_evidence": evidence, "results": results})
    print(len(coverage), "FMZ recipe trials,", len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("public_params", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    run(options.scratch, options.public_params, options.output)
