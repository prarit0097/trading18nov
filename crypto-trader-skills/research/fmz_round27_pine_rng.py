"""Validate the authored unseeded strategies in a prespecified stochastic ensemble."""

from __future__ import annotations

import argparse
import csv
import io
import re
from collections import deque
from datetime import UTC, datetime
from math import fsum
from pathlib import Path
from shutil import copy2
from statistics import quantiles
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256, verified_archives
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal, relative_strength

CAPITAL = 1_000_000
TRIALS = 32
DAY = 86_400_000
HOUR = 3_600_000
MARKETS = ("BTCUSDT", "ETHUSDT")
MODEL = {"native": "FMZ native window", "next": "Next equal window"}
GROUP = "FMZ Pine · Prespecified seed and stochastic ensemble"
NATIVE_BINARY_HASH = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
SPECS = {
    1514: ("2024-02-21", "2025-02-18", "1d", DAY, "Binance", "08:00:00"),
    5755: ("2024-06-30", "2024-07-30", "1h", HOUR, "Futures_Binance", "00:00:00"),
}


def pinned_source(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    source = {r["id"]: r for r in read(baseline)["disposition"] if r["id"] in SPECS}
    assert set(source) == set(SPECS)
    assert all(r["status"].startswith("Pending") for r in source.values())
    with ZipFile(archive) as fmz:
        for ident, row, document, digest in documents(fmz, source):
            (raw,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
            )
            assert "//@version=5" in raw
            start, end, interval, _, venue, end_clock = SPECS[ident]
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    raw,
                )
            )
            assert fields == {
                "start": start + " 00:00:00",
                "end": f"{end} {end_clock}",
                "period": interval,
                "basePeriod": "1d" if ident == 1514 else "15m",
                "exchanges": f'[{{"eid":"{venue}","currency":"BTC_USDT"}}]',
            }
            active = "\n".join(executable_lines(raw))
            if ident == 1514:
                required = (
                    "emaPeriod = 200",
                    "smaPeriod = 200",
                    "prediction = math.random() * 2 - 1",
                    "isNewBuySignal = prediction > 0 and isEmaUptrend and isSmaUptrend",
                    "isNewSellSignal = prediction < 0 and isEmaDowntrend and isSmaDowntrend",
                    "endLongTradeStrict = barsHeld == 4 and isNewBuySignal[1]",
                    "endShortTradeStrict = barsHeld == 4 and isNewSellSignal[1]",
                    "strategy.close_all()",
                )
            else:
                required = (
                    "ta.crossover(shortMovingAverage, longMovingAverage) and rsi < rsiOverbought",
                    "ta.crossunder(shortMovingAverage, longMovingAverage) and rsi > rsiOversold",
                    "bullishToBearishProb = 0.2",
                    "bullishToNeutralProb = 0.5",
                    "bearishToBullishProb = 0.3",
                    "bearishToNeutralProb = 0.4",
                    "neutralToBullishProb = 0.3",
                    "neutralToBearishProb = 0.2",
                    'strategy.close("Long")',
                    'strategy.close("Short")',
                )
            assert all(token in active for token in required)
            assert active.count("math.random()") == (1 if ident == 1514 else 6)
            assert active.count("strategy.entry(") == 2
            yield ident, row, digest, fields, raw.encode()


def spot_daily(files):
    for path in files:
        with ZipFile(path) as archive:
            (name,) = archive.namelist()
            with archive.open(name) as source:
                for bar in csv.reader(io.TextIOWrapper(source, encoding="ascii")):
                    if not bar[0].isdigit():
                        continue
                    raw = int(bar[0])
                    factor = 1000 if raw >= 1_735_689_600_000_000 else 1
                    at = raw // factor
                    assert raw == at * factor and int(bar[6]) == (at + DAY) * factor - 1
                    o, h, low, c, volume = map(float, bar[1:6])
                    assert 0 < low <= min(o, c) <= max(o, c) <= h and volume > 0
                    yield at, o, h, low, c, volume


def inputs(ident, spot, futures):
    start, end, interval, step, _, _ = SPECS[ident]
    lo, hi = map(date_ms, (start, end))
    upper = hi * 2 - lo
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(lo, upper, step)
        }
    )
    evidence, data = [], {"native": {}, "next": {}}
    for market in MARKETS:
        archives = verified_archives(
            spot if ident == 1514 else futures, market, interval, months, evidence
        )
        tape = (
            list(spot_daily(archives))
            if ident == 1514
            else [r for path in archives for r in provider_bars(path, step)]
        )
        for name, left, right in (("native", lo, hi), ("next", hi, upper)):
            candles = [list(r) for r in tape if left <= r[0] < right]
            assert [r[0] for r in candles] == list(range(left, right, step))
            data[name][market] = candles
    if ident == 1514:
        for item in evidence:
            item["url"] = item["url"].replace("/futures/um/", "/spot/", 1)
    return evidence, data


def stage(archive, baseline, work, spot, futures):
    for ident, _, _, _, raw in pinned_source(archive, baseline):
        _, data = inputs(ident, spot, futures)
        (work / f"r27-rng-{ident}.pine").write_bytes(raw)
        write(work / f"r27-rng-{ident}-feeds.json", data)
    replay = Path(__file__).with_name("fmz_round27_pine_rng_probe.py")
    copy2(replay, work / "r27_rng_probe.py")


MASK = (1 << 64) - 1


def sequence(seed):
    word = (seed + 0x9E3779B97F4A7C15) & MASK
    word = ((word ^ (word >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    word = ((word ^ (word >> 27)) * 0x94D049BB133111EB) & MASK
    state = word ^ (word >> 31)
    while True:
        state = (state * 6364136223846793005 + 1442695040888963407) & MASK
        yield (state >> 11) / 2**53


def threshold_states(candles, trial):
    price = [x[4] for x in candles]
    rsi = relative_strength(price, 14)
    d10, d50 = deque(maxlen=10), deque(maxlen=50)
    before = None
    random = [sequence(trial * 65537 + i * 8191) for i in range(6)]
    probabilities = ((0.2, 0.5, 2, 3, 1), (0.3, 0.4, 1, 3, 2), (0.3, 0.2, 1, 2, 3))
    for p, r in zip(price, rsi, strict=True):
        d10.append(p)
        d50.append(p)
        diff = fsum(d10) / 10 - fsum(d50) / 50 if len(d50) == 50 else None
        bull = (
            diff is not None
            and before is not None
            and diff > 0
            and before <= 0
            and r < 70
        )
        bear = (
            diff is not None
            and before is not None
            and diff < 0
            and before >= 0
            and r > 30
        )
        before = diff
        regime = 0 if bull else 1 if bear else 2
        probability1, probability2, a, b, c = probabilities[regime]
        result = (
            a
            if next(random[2 * regime]) < probability1
            else b
            if next(random[2 * regime + 1]) < probability2
            else c
        )
        yield (result, regime + 1), (1 if result == 1 else -1 if result == 2 else 0)


def predictions(candles, trial):
    past = deque(maxlen=200)
    ema_value = None
    rng = sequence(trial * 65537)
    local_position = False
    direction = 0
    held_bars = 0
    previous_buy = previous_sell = False
    for _, _, _, _, price, _ in candles:
        past.append(price)
        ema_value = (
            price if ema_value is None else ((2 * price + 199 * ema_value) / 201)
        )
        sma = fsum(past) / 200 if len(past) == 200 else None
        value = next(rng) * 2 - 1
        buy = sma is not None and value > 0 and price > ema_value and price > sma
        sell = sma is not None and value < 0 and price < ema_value and price < sma
        if (buy or sell) and not local_position:
            held_bars = 1
            local_position = True
        elif local_position:
            held_bars += 1
            if held_bars == 4:
                local_position = False
        long_exit = held_bars == 4 and previous_buy
        short_exit = held_bars == 4 and previous_sell
        if buy and direction <= 0:
            direction = 1
        if sell and direction >= 0:
            direction = -1
        if (long_exit and direction == 1) or (short_exit and direction == -1):
            direction = 0
        previous_buy, previous_sell = buy, sell
        yield (
            (ema_value, sma, value, buy, sell, long_exit, short_exit, direction),
            direction,
        )


def broker(candles, states):
    positions = []
    direction = 0
    index = None
    tr = []
    desired = 0
    for i, (_, op, _, _, _, _) in enumerate(candles):
        if direction != desired:
            if direction:
                entry = candles[index][1]
                tr.append((direction, index, i, entry, op))
            direction = desired
            index = i
        positions.append(direction)
        desired = states[i][1]
    return positions, tr


PLOTS = {
    1514: (
        "EMA",
        "SMA",
        "Prediction",
        "Buy",
        "Sell",
        "Strict long exit",
        "Strict short exit",
        "Direction",
    ),
    5755: ("Next state", "Current state"),
}


def check_trial(ident, chart, record):
    strategy = predictions if ident == 1514 else threshold_states
    decisions = list(strategy(chart, record["trial"]))
    witnessed = record["observations"]
    for index, (want, received) in enumerate(
        zip(
            (r[0] for r in decisions),
            zip(*(witnessed[name] for name in PLOTS[ident]), strict=True),
            strict=True,
        )
    ):
        assert all(equal(a, b) for a, b in zip(want, received, strict=True)), (
            ident,
            record["trial"],
            index,
            want,
            received,
        )
    sizes, trades = broker(chart, decisions)
    assert sizes == witnessed["Position"]
    realized = []
    for want, got in zip(trades, record["trades"], strict=True):
        side, entry_i, exit_i, entry, exit = want
        turnover = entry + exit
        gross = side * (exit - entry)
        fee = FEE * turnover
        values = tuple(
            got[key]
            for key in (
                "qty",
                "entryBarIndex",
                "exitBarIndex",
                "entryPrice",
                "exitPrice",
                "profit",
            )
        )
        reference = (*want, gross - fee)
        assert all(equal(a, b) for a, b in zip(reference, values, strict=True)), (
            want,
            values,
        )
        assert (
            got["entryTime"] == chart[entry_i][0]
            and got["exitTime"] == chart[exit_i][0]
        )
        assert got["id"] == ("Long" if side > 0 else "Short")
        realized.append((got["exitTime"], gross, fee, turnover * EXECUTION))
    for order in record["orders"]:
        index = order["barIndex"]
        assert chart[index][0] == order["time"] and equal(
            chart[index][1], order["price"]
        )
    return realized, int(bool(sizes[-1]))


def ensemble(trials):
    keys = ("trades", "gross", "after_fees", "net", "gross_dd", "fee_dd", "net_dd")
    metrics = []
    assert len(trials) == TRIALS
    for i, result in enumerate(trials, 1):
        count = result["trades"]
        metrics.append(
            {
                "trial": i,
                **result,
                "gross_win_rate": result["gross_wins"] / count if count else None,
                "after_fees_win_rate": result["fee_wins"] / count if count else None,
                "net_win_rate": result["net_wins"] / count if count else None,
            }
        )
    bands = {}
    for key in (*keys, "gross_win_rate", "after_fees_win_rate", "net_win_rate"):
        observed = [row[key] for row in metrics if row[key] is not None]
        if len(observed) >= 2:
            p = quantiles(observed, n=100, method="inclusive")
            bands[key] = {"p05": p[4], "median": p[49], "p95": p[94]}
    return {
        "trial_metrics": metrics,
        "seed_ensemble_quantiles": bands,
        "positive_after_fees_trials": sum(m["after_fees"] > 0 for m in metrics),
        "positive_net_trials": sum(m["net"] > 0 for m in metrics),
    }


def report(archive, baseline, work, spot, futures, output):
    binary = work / "priced-runtime/pine_compat/pine_compat.pyd"
    assert sha256(binary) == NATIVE_BINARY_HASH
    isolate = read(work / "round3-isolation-python.json")
    assert all(
        isolate[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    producer = Path(__file__).with_name("fmz_round27_pine_rng_probe.py")
    assert producer.read_bytes() == (work / "r27_rng_probe.py").read_bytes()
    rows, coverage, statistics = [], [], []
    manifest, artifacts, source_audits = {}, {}, {}
    for ident, original, digest, fields, raw in pinned_source(archive, baseline):
        manifest[ident], data = inputs(ident, spot, futures)
        archived = work / f"r27-rng-{ident}.pine"
        feed = work / f"r27-rng-{ident}-feeds.json"
        receipt = work / f"r27-rng-{ident}-{TRIALS}-receipt.json"
        assert archived.read_bytes() == raw and read(feed) == data
        records = read(receipt)
        expected_seeds = set(range(1, TRIALS + 1))
        replay = {(x["period"], x["market"], x["trial"]): x for x in records}
        assert len(replay) == len(records) == 2 * 2 * TRIALS
        assert set(replay) == {
            (w, m, s) for w in MODEL for m in MARKETS for s in expected_seeds
        }
        prefix = next(r["seeded_source_sha256"] for r in records if r["trial"] == 1)
        source_audits[ident] = {
            "archive_settings": fields,
            "source_document_sha256": digest,
            "archived_pine_sha256": sha256(archived),
            "seed_1_executed_pine_sha256": prefix,
            "seed_executed_sha256": {
                str(s): next(
                    r["seeded_source_sha256"] for r in records if r["trial"] == s
                )
                for s in sorted(expected_seeds)
            },
        }
        for r in records:
            assert (
                r["seeded_source_sha256"]
                == source_audits[ident]["seed_executed_sha256"][str(r["trial"])]
            )
        coverage.append(
            [
                ident,
                f"Tested · {GROUP}",
                "Original random draw was unseeded. An independently reconciled 32-seed benchmark reports sensitivity over the same historical data, and the workbook uses prespecified seed 1.",
            ]
        )
        artifacts.update({f.name: sha256(f) for f in (archived, feed, receipt)})
        interval = SPECS[ident][2]
        common = {
            "id": ident,
            "name": original["name"],
            "source": original["source"],
            "source_sha256": digest,
            "executed_source_sha256": prefix,
            "group": GROUP,
            "interval": interval,
            "archive_interval": interval,
            "quote_currency": "USDT",
            "market_data": "Binance Spot daily USDT marks"
            if ident == 1514
            else "Official Binance USD-M hourly OHLCV",
            "exit": "Author's strict exit or opposite entry"
            if ident == 1514
            else "Author's random threshold state transition or explicit close",
            "seed": 1,
        }
        for w, markets in data.items():
            pooled = [([], 0) for _ in range(TRIALS)]
            for m, chart in markets.items():
                trials = []
                for index, trial in enumerate(sorted(expected_seeds)):
                    cashflows, open_lots = check_trial(
                        ident, chart, replay[(w, m, trial)]
                    )
                    accum, open_count = pooled[index]
                    pooled[index] = (accum + cashflows, open_count + open_lots)
                    trials.append(summarize(cashflows, open_lots, CAPITAL))
                rows.append({**common, "period": MODEL[w], "market": m, **trials[0]})
                statistics.append(
                    {
                        "id": ident,
                        "period": MODEL[w],
                        "market": m,
                        "chart_bars_per_trial": len(chart),
                        **ensemble(trials),
                    }
                )
            pooled_results = [
                summarize(cashflows, open_lots, 2 * CAPITAL)
                for cashflows, open_lots in pooled
            ]
            market = "BTCUSDT + ETHUSDT"
            rows.append(
                {**common, "period": MODEL[w], "market": market, **pooled_results[0]}
            )
            statistics.append(
                {
                    "id": ident,
                    "period": MODEL[w],
                    "market": market,
                    "chart_bars_per_trial": sum(len(x) for x in markets.values()),
                    **ensemble(pooled_results),
                }
            )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "native_isolation_probe": isolate,
            "pine_compat_binary_sha256": sha256(binary),
            "native_runner_sha256": sha256(producer),
            "source_audits": source_audits,
            "provider_archives": manifest,
            "artifacts": artifacts,
            "cost_model": {"fee_per_side": FEE, "execution_buffer_per_side": EXECUTION},
            "references": [
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/pine-script-reference/v5/#fun_math.random",
                "https://www.tradingview.com/pine-script-reference/v5/#fun_ta.ema",
                "https://www.tradingview.com/support/solutions/43000628599-strategy-properties/",
            ],
            "method": [
                "Both archived scripts call math.random without a seed. Each scenario uses prespecified trials 1–32. The seed at each source call site is trial×65,537 + site×8,191. That makes 128 reproducible scenarios for each strategy. A separate Python calculation reproduces Pine Compat's unit random stream, original filter and state transitions, and reconciles every closed lot, bar position and fill price.",
                "Seed 1 supplies each workbook row and was selected before scoring. The 32-seed distributions quantify sensitivity on the same dated sequence. Percentiles and positive-trial counts describe variation across random draws under these rules. They give no additional independent market samples.",
                "Strategy 1514's EMA uses TradingView's documented first-price seed and recurrence. Pine Compat's built-in seeds with an SMA, so that operation runs as its explicit documented recurrence. The native window uses only fully completed daily spot candles through the 08:00 UTC cutoff. Short directions remain hypothetical exposures to the same Binance spot marks, without spot borrow costs.",
                "Strategy 5755 retains its authored sequence of separate conditional probability draws. Its archived volatility values do not gate orders. Same-market OHLCV, next-open fills, fixed one-unit sizing and documented 1,000,000 starting capital are used. Both strategies use the stated fees and additional execution allowance. Funding and borrow cashflows are outside the model.",
            ],
            "stochastic_ensemble": statistics,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified 2 strategy IDs, {len(rows)} workbook rows and {2 * 2 * 2 * TRIALS} seeded trials."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for arg in ("archive", "baseline", "work", "spot", "futures", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    args = parser.parse_args()
    paths = (args.archive, args.baseline, args.work, args.spot, args.futures)
    if args.mode == "stage":
        stage(*paths)
    else:
        report(*paths, args.output)


if __name__ == "__main__":
    main()
