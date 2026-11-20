"""Replay explicit variants of five documented TradingView strategy concepts."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from research.delta_pine_liquid_replay import archived_candles
from research.delta_pinets_catalogue import read, write
from research.fmz_marketdata_replay import market_windows

VARIANTS = {
    6035: (
        "20-bar Bollinger Bands, long on a close crossing below the lower band. Next-open exit on middle-band recovery, with a two-ATR stop.",
        """
basis = ta.sma(close, 20)
lower = basis - 2 * ta.stdev(close, 20)
distance = math.max(1, math.round(2 * ta.atr(14) / syminfo.mintick))
if ta.crossunder(close, lower) and strategy.position_size == 0
    strategy.entry("Long", strategy.long)
    strategy.exit("Stop", "Long", loss=distance)
if close >= basis
    strategy.close("Long")
""",
    ),
    6040: (
        "Strict inside candle followed by a confirmed mother-bar breakout. Stop distance uses the opposite mother-bar extreme, with a one-R target.",
        """
inside = high[1] < high[2] and low[1] > low[2]
if inside and close > high[2] and strategy.position_size == 0
    distance = math.max(1, math.round((close - low[2]) / syminfo.mintick))
    strategy.entry("Long", strategy.long)
    strategy.exit("Bracket long", "Long", loss=distance, profit=distance)
if inside and close < low[2] and strategy.position_size == 0
    distance = math.max(1, math.round((high[2] - close) / syminfo.mintick))
    strategy.entry("Short", strategy.short)
    strategy.exit("Bracket short", "Short", loss=distance, profit=distance)
""",
    ),
    6047: (
        "Retest the previous UTC day's classic pivot, then close back on the approach side. The prior day's first support and resistance set the stop and target.",
        """
prevH = request.security(syminfo.tickerid, "D", high[1], lookahead=barmerge.lookahead_on)
prevL = request.security(syminfo.tickerid, "D", low[1], lookahead=barmerge.lookahead_on)
prevC = request.security(syminfo.tickerid, "D", close[1], lookahead=barmerge.lookahead_on)
pp = (prevH + prevL + prevC) / 3
s1 = 2 * pp - prevH
r1 = 2 * pp - prevL
if open > pp and low <= pp and close > pp and close < r1 and strategy.position_size == 0
    strategy.entry("Long", strategy.long)
    strategy.exit("Bracket long", "Long", stop=s1, limit=r1)
if open < pp and high >= pp and close < pp and close > s1 and strategy.position_size == 0
    strategy.entry("Short", strategy.short)
    strategy.exit("Bracket short", "Short", stop=r1, limit=s1)
""",
    ),
    6050: (
        "14-bar Stochastic with 3-bar smoothing. Long when slow K crosses up through 20 and short when it crosses down through 80. Opposite signal reverses.",
        """
slow = ta.sma(ta.stoch(close, high, low, 14), 3)
if ta.crossover(slow, 20)
    strategy.entry("Long", strategy.long)
if ta.crossunder(slow, 80)
    strategy.entry("Short", strategy.short)
""",
    ),
    6052: (
        "Documented moving-averages rating group with 15 votes and unshifted Ichimoku levels. Strong signals at +/-0.5. Fixed 3 ATR loss and 5 ATR trail activation with 2 ATR offset, frozen at entry.",
        """
vote(ma) => close > ma ? 1 : close < ma ? -1 : 0
conversion = (ta.highest(high, 9) + ta.lowest(low, 9)) / 2
baseLine = (ta.highest(high, 26) + ta.lowest(low, 26)) / 2
spanA = (conversion + baseLine) / 2
spanB = (ta.highest(high, 52) + ta.lowest(low, 52)) / 2
bull = spanA > spanB and baseLine > spanA and conversion > baseLine and close > conversion
bear = spanA < spanB and baseLine < spanA and conversion < baseLine and close < conversion
ichi = bull ? 1 : bear ? -1 : 0
v1 = vote(ta.sma(close, 10)) + vote(ta.sma(close, 20)) + vote(ta.sma(close, 30)) + vote(ta.sma(close, 50)) + vote(ta.sma(close, 100)) + vote(ta.sma(close, 200))
v2 = vote(ta.ema(close, 10)) + vote(ta.ema(close, 20)) + vote(ta.ema(close, 30)) + vote(ta.ema(close, 50)) + vote(ta.ema(close, 100)) + vote(ta.ema(close, 200))
rating = (v1 + v2 + vote(ta.hma(close, 9)) + vote(ta.vwma(close, 20)) + ichi) / 15.0
atr = ta.atr(14) / syminfo.mintick
ready = not na(ta.sma(close, 200))
if ready and ta.crossover(rating, 0.5) and strategy.position_size <= 0
    strategy.entry("Long", strategy.long)
    strategy.exit("Risk long", "Long", loss=math.round(3 * atr), trail_points=math.round(5 * atr), trail_offset=math.round(2 * atr))
if ready and ta.crossunder(rating, -0.5) and strategy.position_size >= 0
    strategy.entry("Short", strategy.short)
    strategy.exit("Risk short", "Short", loss=math.round(3 * atr), trail_points=math.round(5 * atr), trail_offset=math.round(2 * atr))
""",
    ),
}


def prepare(prior, backlog, work):
    base = {r["id"]: r for r in read(backlog)["disposition"]}
    items = []
    for ident, (method, signals) in VARIANTS.items():
        row = base[ident]
        assert row["status"] == "TradingView source pending"
        assert row["source"].startswith("https://www.tradingview.com/support/")
        with urlopen(row["source"], timeout=30) as response:
            doc = response.read()
        code = (
            f'//@version=5\nstrategy("Documented variant {ident}")\n'
            + signals.strip()
            + "\n"
        )
        items.append(
            {
                "id": ident,
                "name": row["name"],
                "source": row["source"],
                "archived": "Help Center",
                "code": code,
                "method": method,
                "hash": hashlib.sha256(doc).hexdigest(),
                "variant_sha256": hashlib.sha256(code.encode()).hexdigest(),
                "timeoutMs": 60_000,
            }
        )
    market, archives = archived_candles(prior / "liquid-reviewed")
    bar_data, windows = market_windows(market, minutes=15)
    write(work / "candidates.json", items)
    write(work / "candles.json", bar_data)
    write(work / "inputs.json", {"market_archives": archives, "windows": windows})


def finalize(work, out):
    probe = read(work / "isolation-probe.json")
    assert probe == {"privateDenied": True, "networkDenied": True}
    prepared = {x["id"]: x for x in read(work / "candidates.json")}
    records = list(
        map(
            json.loads,
            (work / "out.jsonl").read_text(encoding="utf-8-sig").splitlines(),
        )
    )
    assert len(prepared) == len(records) == len({r["id"] for r in records})
    coverage, results = [], []
    for record in records:
        ident = record["id"]
        candidate = prepared[ident]
        if issue := record.get("reason"):
            coverage.append([ident, "TradingView variant pending", issue])
            continue
        rows = record["results"]
        assert len(rows) == 6 and all(
            r["source_sha256"] == candidate["hash"] for r in rows
        )
        for row in rows:
            row.update(
                group="TradingView · documented variant",
                quote_currency="USDT",
                market_data="Binance USD-M perpetuals",
                repairs=candidate["method"],
            )
        results.extend(rows)
        suffix = "" if any(r["trades"] for r in rows) else ", no closes"
        coverage.append(
            [
                ident,
                "Tested · TradingView documented variant" + suffix,
                candidate["method"],
            ]
        )
    write(
        out,
        {
            **read(work / "inputs.json"),
            "isolation_probe": probe,
            "documented_variants": [
                {k: v for k, v in item.items() if k != "code"}
                for item in prepared.values()
            ],
            "coverage": coverage,
            "results": results,
        },
    )
    print(f"{len(results) // 6} documented TradingView variants measured", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    for key in ("prior", "backlog", "work"):
        prep.add_argument(key, type=Path)
    finish = sub.add_parser("finalize")
    finish.add_argument("work", type=Path)
    finish.add_argument("out", type=Path)
    args = vars(parser.parse_args())
    action = args.pop("action")
    (prepare if action == "prepare" else finalize)(**args)
