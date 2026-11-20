"""Audit and replay Zenbot ta_ppo signals without its retired Node addon."""

import argparse
import hashlib
import itertools
import math
from collections import deque
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics

IDENT = 5901
IDLE = None
RSI_N = 25
STAKE, FEE, EXECUTION = 1000, 0.00059, 0.00030


def ppo(closes):
    short = math.fsum(closes[-12:]) / 12
    long = math.fsum(closes[-26:]) / 26
    return 100 * (short - long) / long


def rsi(history, current, gain, loss):
    if gain is None:
        seed = list(history)[-RSI_N:]
        moves = [b - a for a, b in itertools.pairwise(seed)]
        gain = math.fsum(max(x, 0) for x in moves) / RSI_N
        loss = math.fsum(max(-x, 0) for x in moves) / RSI_N
    else:
        move = current - history[-1]
        gain = ((RSI_N - 1) * gain + max(move, 0)) / RSI_N
        loss = ((RSI_N - 1) * loss + max(-move, 0)) / RSI_N
    value = (
        100
        if not loss
        else math.floor((100 - 100 / (1 + gain / loss)) * 100 + 0.5) / 100
    )
    return value, gain, loss


def replay(bars):
    history, market, rows, ledger = deque(maxlen=1000), [], [], []
    gain = loss = active = pending = previous_ppo = IDLE
    for bar in bars:
        assert bar["volume"] > 0
        start, current = bar["open"], bar["close"]
        if pending == "buy" and active is IDLE:
            active = (bar["openTime"], start)
        elif pending == "sell" and active is not IDLE:
            at, entry = active
            qty = STAKE / entry
            turnover = qty * (start + entry)
            gross = qty * (start - entry)
            rows.append((bar["openTime"], gross, turnover * FEE, turnover * EXECUTION))
            ledger.append([at, bar["openTime"], entry, start])
            active = IDLE
        pending = current_ppo = IDLE
        overbought = False
        if len(history) >= RSI_N:
            value, gain, loss = rsi(history, current, gain, loss)
            overbought = value >= 70
        ready = len(history) >= 52
        if ready and overbought:
            pending = "sell"
        else:
            added = len(history) - len(market)
            if added > 0:
                market.extend(list(history)[-added:])
            if len(market) >= 34:
                current_ppo = ppo([*market[-25:], current])
                if ready and current_ppo and previous_ppo:
                    pending = "buy" if current_ppo >= 0 else "sell"
        history.append(current)
        previous_ppo = current_ppo
    return rows, int(active is not IDLE), ledger


def run(archive_path, candles, baseline, output):
    item = {x["id"]: x for x in read(baseline)["disposition"]}[IDENT]
    assert not item["status"].startswith("Tested")
    ref = item["source"].split("/blob/")[1].split("/")[0]
    with ZipFile(archive_path) as archive:
        files = [
            name
            for name in archive.namelist()
            if name.endswith(
                (
                    "/extensions/strategies/ta_ppo/strategy.js",
                    "/lib/ta_ppo.js",
                    "/lib/rsi.js",
                )
            )
        ]
        assert len(files) == 3 and all(
            name.startswith("zenbot-" + ref + "/") for name in files
        )
        inputs = {
            file: hashlib.sha256(archive.read(file)).hexdigest() for file in files
        }
    rows, evidence = [], {}
    for period, markets in read(candles).items():
        series = []
        for coin, segments in markets.items():
            [bars] = segments
            closed, unsettled, ledger = replay(bars)
            evidence[f"{period}/{coin}"] = ledger
            series.append((coin + "/USDT", closed, unsettled))
        assert len(series) == 2
        series.append(
            ("BTC + ETH", series[0][1] + series[1][1], series[0][2] + series[1][2])
        )
        for market, closed, unsettled in series:
            rows.append(
                {
                    "id": IDENT,
                    "name": item["name"],
                    "source": item["source"],
                    "period": period,
                    "group": "Zenbot · PPO signal variant",
                    "market": market,
                    "currency": "USDT",
                    "interval": "15m",
                    "archive_interval": "10m source default",
                    "exit": "Sell advice at next open",
                    **metrics(closed, unsettled),
                }
            )
    assert len(rows) == 6
    suff = "" if any(r["trades"] for r in rows) else ", no closes"
    write(
        output,
        {
            "source_sha256": inputs,
            "spot_candle_sha256": hashlib.sha256(candles.read_bytes()).hexdigest(),
            "fills": evidence,
            "results": rows,
            "coverage": [
                [
                    IDENT,
                    "Tested · Zenbot PPO signal variant" + suff,
                    "Pinned SMA-PPO and overbought RSI logic reproduced with the prior 15m Binance spot, long-only next-open execution model.",
                ]
            ],
        },
    )
    print(
        f"Zenbot PPO replay verified {sum(len(ledger) for ledger in evidence.values())} closes"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive_path", "candles", "baseline", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
