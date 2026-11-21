"""Independently verify two original FMZ reversal strategies on the dated BTC case."""

import gzip
import hashlib
import json
import random
import sys
from decimal import Decimal as D
from itertools import pairwise
from pathlib import Path

ZERO = D(0)
CAPITAL = D("0.1")
VALUE = D(100)
FEE = D("0.0005")
TICK = D("0.01")
BEGIN, END = 1567317600000, 1567375200000
INPUT_SHA = "11f3c32156cc63a73f712d65343b706a37acdb1f7dcb9f0421ccaca099e1a5cf"
IDS = ((666, 0), (667, 0), (667, 1), (667, 2))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def close(left, right):
    assert abs(left - right) < D("0.000000005"), (left, right)


def first_signal(records, minutes):
    assert len(records) == 25 and records[-1]["Time"] == BEGIN
    for record in records[:-1]:
        start = record["Time"]
        window = [
            minutes[t] for t in range(start, start + 900000, 60000) if t in minutes
        ]
        prices = [
            window[0][1],
            max(r[2] for r in window),
            min(r[3] for r in window),
            window[-1][4],
        ]
        assert [D(p) / 100 for p in prices] == [
            record[n] for n in ("Open", "High", "Low", "Close")
        ]
    assert records[-1]["Volume"] == 0
    assert records[-1]["Close"] == D(minutes[BEGIN][1]) / 100
    closes = [r["Close"] for r in records]
    changes = [b - a for a, b in pairwise(closes)]
    gain = sum(max(v, ZERO) for v in changes[:14]) / 14
    loss = sum(max(-v, ZERO) for v in changes[:14]) / 14
    values = []
    for v in changes[14:]:
        gain = (13 * gain + max(v, ZERO)) / 14
        loss = (13 * loss + max(-v, ZERO)) / 14
        values.append(100 * gain / (gain + loss) if gain + loss else ZERO)
    return ("buy" if values[-2] < values[-1] else "sell"), values[-2:]


def verify_case(r, model, market):
    minutes = {t[0]: t for t in market}
    assert r["input_sha256"] == INPUT_SHA and END - 30000 <= r["source_cutoff"] < END
    assert r["choices"] == [
        {
            "InstrumentID": "BTC-USD-190906",
            "LotTick": 1,
            "PriceTick": TICK,
            "VolumeMultiple": VALUE,
        }
    ]
    ident, seed = r["id"], r["seed"]
    if ident == 666:
        first, signal = first_signal(r["first_records"], minutes)
    else:
        rolled = random.Random(seed).choice([1, 2, 3, 4, 5, 6])
        first, signal = ("buy" if rolled % 2 else "sell"), [rolled]
    assert r["submitted"][0][2] == first
    fills = []
    open_price, open_fee, gross, accounted_fees, closed = ZERO, ZERO, ZERO, ZERO, 0
    position = 0
    for submission, order in zip(r["submitted"], r["orders"], strict=True):
        before, stamp, direction, requested, qty, ticket = submission
        assert (
            order["Id"] == ticket and order["Time"] == stamp and before <= stamp < END
        )
        assert order["Status"] == 1 and order["Amount"] == order["DealAmount"] == qty
        price = order["AvgPrice"]
        side = 1 if direction in ("buy", "closesell") else -1
        assert order["Type"] == int(side < 0) and order["Offset"] == int(
            direction.startswith("close")
        )
        assert side * (price - requested) <= TICK
        bar = minutes[stamp // 60000 * 60000]
        assert D(bar[3]) / 100 - TICK <= price <= D(bar[2]) / 100 + TICK and bar[5] > 0
        charge = FEE * VALUE * qty / price
        accounted_fees += charge
        if direction.startswith("close"):
            assert open_price > 0 and qty == abs(position) and side * position < 0
            stop_quote = requested / (D("1.01") if side == 1 else D("0.99"))
            assert (
                (stop_quote > open_price * D("1.015"))
                if side == 1
                else (stop_quote < open_price * D("0.985"))
            )
            gross = (D(1) / open_price - D(1) / price) * position * VALUE
            closed_fee = open_fee + charge
            closed = 1
            position = 0
        else:
            assert position == 0 and qty == (2 if closed else 1)
            open_price, open_fee, position = price, charge, int(side * qty)
        fills.append([stamp, direction, int(qty), str(price), str(charge)])
    [held] = r["held"]
    assert held["MarginLevel"] == 20 and held["Amount"] == abs(position)
    assert (held["Type"] == 0) == (position > 0)
    close(held["Price"], open_price)
    close(held["Margin"], VALUE * abs(position) / open_price / 20)
    balance = r["account"]
    close(balance["Stocks"] + held["Margin"], CAPITAL + gross - accounted_fees)
    close(balance["Equity"], CAPITAL + gross - accounted_fees + held["Profit"])
    mark = 1 / (1 / open_price - held["Profit"] / (VALUE * position))
    anchor = r["source_cutoff"] // 60000 * 60000
    edge = [b for t, b in minutes.items() if anchor <= t <= END + 60000]
    assert (
        min(D(b[3]) / 100 for b in edge) - TICK
        <= mark
        <= max(D(b[2]) / 100 for b in edge) + TICK
    )
    fees = closed_fee if closed else ZERO
    net = gross - fees
    result = {
        "id": ident,
        "group": "Original Python / dated OKCoin weekly",
        "market": "OKEX dated BTC-USD-190906 inverse current-week",
        "period": "2019-09-01 06:00–22:00 UTC",
        "interval": "Native 1m simulated ticks and 30s author pause",
        "exit": "Authored reversal by stop or close with seeded initial entry",
        "currency": "BTC",
        "starting_equity": float(CAPITAL),
        "trades": closed,
        "unsettled": 1,
        "gross_wins": int(gross > 0),
        "fee_wins": int(net > 0),
        "net_wins": int(net > 0),
        "gross": float(gross),
        "fees": float(fees),
        "after_fees": float(net),
        "net": float(net),
        "execution": 0,
        "funding": 0,
        "gross_dd": float(max(ZERO, -gross)),
        "fee_dd": float(max(ZERO, -net)),
        "net_dd": float(max(ZERO, -net)),
        "net_dd_pct": float(max(ZERO, -net) / CAPITAL),
        "total_fee_BTC": float(accounted_fees),
        "terminal_marked_PnL_BTC": float(balance["Equity"] - CAPITAL),
        "source": model["source_url"],
    }
    if ident == 666:
        result["exit"] = "15m RSI entry, then authored stop and reversal"
    else:
        result["exit"] = f"Authored die roll seed {seed}, then original reversal rules"
    return result, {
        "first_signal": first,
        "signal_witness": [str(v) for v in signal],
        "fills": fills,
        "ending_contracts": position,
    }


def main(directory, worker, output):
    raw = (directory / "round50-666-667-input.json.gz").read_bytes()
    worker_bytes = worker.read_bytes()
    assert sha(raw) == INPUT_SHA
    inputs = json.loads(gzip.decompress(raw))
    results, proofs = [], []
    for ident, seed in IDS:
        a, b = [
            (directory / f"round50-{ident}-{seed}-{tag}.json").read_bytes()
            for tag in ("first", "repeat")
        ]
        first, repeat = [json.loads(k, parse_float=D) for k in (a, b)]
        assert first["id"] == ident and first["seed"] == seed
        assert {k: v for k, v in first.items() if k != "requests"} == {
            k: v for k, v in repeat.items() if k != "requests"
        }
        r, proof = verify_case(
            first, inputs["sources"][str(ident)], inputs["market"]["data"]
        )
        proofs.append(
            {
                "id": ident,
                "seed": seed,
                "run_sha256": sha(a),
                "repeat_sha256": sha(b),
                **proof,
            }
        )
        if ident == 667 and seed == 1:
            assert {k: v for k, v in r.items() if k != "exit"} == {
                k: v for k, v in results[-1].items() if k != "exit"
            }
            results[-1]["exit"] = (
                "Equivalent die-roll seeds 0 and 1, then authored reversal"
            )
        else:
            results.append(r)
    output.write_text(
        json.dumps(
            {
                "schema": "FMZ original Python Levy fixed weekly replay",
                "input_sha256": INPUT_SHA,
                "worker_sha256": sha(worker_bytes.replace(b"\r\n", b"\n")),
                "executed_worker_sha256": sha(worker_bytes),
                "market_proof": inputs["trade_proof"],
                "publishers": {
                    k: {n: v for n, v in r.items() if n != "source"}
                    for k, r in inputs["sources"].items()
                },
                "cases": proofs,
                "method": "Named current-week inverse BTC instrument. The source defaults retain 20x and one-contract starting size. The calendar, 15m chart, 0.1 BTC wallet, explicit 0.02% maker and 0.05% taker fees and random seeds are study selections. Native simulated subticks and one-tick quote offsets are checked against signed dated trade observations. Marked outcome is separate from settled reductions.",
                "coverage": [
                    [
                        666,
                        "Tested · original RSI and reversal on dated BTC weekly",
                        "Publisher defaults, original Python, an independently reproduced 15m RSI and an inverse-wallet check validate the dated BTC case. The research supplies the calendar, chart period and starting wallet.",
                    ],
                    [
                        667,
                        "Tested · original random and reversal on dated BTC weekly",
                        "Three reproducible seeds cover both sides of the first authored random decision on the same historical tape. Two seeds produce the same result. Open inventory is marked separately.",
                    ],
                ],
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
