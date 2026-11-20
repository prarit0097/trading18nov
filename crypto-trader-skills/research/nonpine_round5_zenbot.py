"""Reconcile the source-pinned Zenbot multi callback replay."""

import argparse
from pathlib import Path

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics
from research.nonpine_round4_zenbot import EXECUTION, FEE, STAKE


def run(raw, baseline, output):
    archive = read(raw)
    assert archive["id"] == 5888
    expected = {5888, 5889}
    catalogue = {
        r["id"]: r for r in read(baseline)["disposition"] if r["id"] in expected
    }
    assert len(catalogue) == len(expected)
    assert all(not r["status"].startswith("Tested") for r in catalogue.values())
    results = []
    for window in archive["results"]:
        market = window["symbol"]
        assert market in {"BTC", "ETH"}
        fills = []
        for at, entry, exit_ in window["trades"]:
            qty = STAKE / entry
            notional = qty * (entry + exit_)
            fills.append(
                (at, qty * (exit_ - entry), notional * FEE, notional * EXECUTION)
            )
        assert fills and window["unsettled"] in (0, 1)
        results.append(
            {
                "id": 5888,
                "period": window["period"],
                "group": "Zenbot · multi callback variant",
                "market": f"{market}/USDT",
                "currency": "USDT",
                "interval": "15m",
                "archive_interval": "30m source default",
                "exit": "Source sell advice at next open",
                **metrics(fills, window["unsettled"]),
            }
        )
    assert len({(r["period"], r["market"]) for r in results}) == len(results) == 4
    write(
        output,
        {
            "coverage": [
                [
                    5888,
                    "Tested · Zenbot multi callback variant",
                    (
                        "Pinned Pivot, MACD, Fisher Transform and Momentum callbacks replayed on 15m Binance spot. "
                        "Cross-realm array detection preserves the Pivot branch. Long-only, next-open fills."
                    ),
                ],
                [
                    5889,
                    "Pending · Zenbot original learning runtime",
                    (
                        "Requires a reproducible ConvNetJS worker lifecycle, training initialization and more than "
                        "2,000 prior 30-minute bars for the original default. Replacing the network changes the strategy."
                    ),
                ],
            ],
            "source_sha256": archive["source_sha256"],
            "candle_sha256": archive["candle_sha256"],
            "settings": {
                "stake": STAKE,
                "fee_per_side": FEE,
                "execution_per_side": EXECUTION,
            },
            "results": results,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("raw", "baseline", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
