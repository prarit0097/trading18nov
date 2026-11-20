"""Reconcile seeded Zenbot neural-worker results with their closed-candle inputs."""

import argparse
import hashlib
import math
from itertools import pairwise
from pathlib import Path

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics
from research.nonpine_round4_zenbot import EXECUTION, FEE, STAKE

IDENT = 5889


def run(root, baseline, output, bars, runtime):
    assert any(
        r["id"] == IDENT and not r["status"].startswith("Tested")
        for r in read(baseline)["disposition"]
    )
    feed = root / "candles.json"
    candles = read(feed)
    candle_hash = hashlib.sha256(feed.read_bytes()).hexdigest()
    results, receipts, source = [], [], None
    for asset in ("BTC", "ETH"):
        suffix = "-direct" if runtime == "direct" else ""
        raw = read(root / f"neural-results-{bars}-{asset}-2026-10-01{suffix}.json")
        assert raw["candle_sha256"] == candle_hash and raw["seed"] == IDENT
        assert raw.get("runtime", "context") == runtime
        [sample] = raw["results"]
        date = "2026-10-01"
        assert sample["market"] == asset and sample["period"] == date
        active_bars = candles[date][asset][2001 : 2001 + bars]
        advice = sample["signals"]
        assert [k["closeTime"] for k in active_bars] == [x[0] for x in advice]
        assert all(math.isfinite(x[2]) and x[1] in ("buy", "sell") for x in advice)
        assert all((b[2] > a[2]) == (b[1] == "buy") for a, b in pairwise(advice))
        reference, active, prior = [], None, None
        for bar, (_, signal, _) in zip(active_bars, advice, strict=True):
            if prior == "buy" and active is None:
                active = (bar["openTime"], bar["open"])
            elif prior == "sell" and active is not None:
                reference.append([active[0], bar["openTime"], active[1], bar["open"]])
                active = None
            prior = signal
        assert reference == sample["trades"] and sample["unsettled"] == int(
            active is not None
        )
        fills = []
        for _, at, entry, exit_ in reference:
            quantity = STAKE / entry
            turnover = quantity * (entry + exit_)
            fills.append(
                (at, quantity * (exit_ - entry), turnover * FEE, turnover * EXECUTION)
            )
        if source is None:
            source = raw["source_hashes"]
        assert raw["source_hashes"] == source
        results.append(
            {
                "id": IDENT,
                "period": date + f" first {bars // 2}h",
                "group": "Zenbot · Seeded neural-worker replay",
                "market": asset + "/USDT",
                "currency": "USDT",
                "interval": "30m",
                "archive_interval": "30m original",
                "exit": "Sell advice at next spot open",
                **metrics(fills, sample["unsettled"]),
            }
        )
        receipts.append(sample)
    status = "Tested · Zenbot seeded neural-worker variant"
    if not any(row["trades"] for row in results):
        status += ", no closes"
    reason = (
        "Pinned Zenbot worker callbacks and ConvNetJS 0.3.0, 2,001-bar warm-up, "
        f"preserved training defaults, fixed PRNG seed and {bars} original-interval 30m BTC/ETH "
        "bars per market. Long-only next-open spot execution and recorded trades."
    )
    write(
        output,
        {
            "coverage": [[IDENT, status, reason]],
            "results": results,
            "source_hashes": source,
            "archive_hashes": read(root / "sources.json"),
            "candle_sha256": candle_hash,
            "receipts": receipts,
            "seed": IDENT,
            "runtime": runtime,
            "sandbox": "AppContainer and Node file permissions",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "baseline", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--bars", type=int, choices=(8, 16, 48), required=True)
    parser.add_argument("--runtime", choices=("direct", "context"), required=True)
    run(**vars(parser.parse_args()))
