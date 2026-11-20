"""Replay documented Deribit combo structures against atomic public trade prints."""

import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

STRUCTURES = (
    "FS CS PS RR RRITM CSR12 CSR13 CSR23 PSR12 PSR13 PSR23 CLAD PLAD STRD STRG GUTS "
    "CBUT PBUT IBUT CBUT111 PBUT111 ICOND CCOND PCOND CCAL PCAL CDIAG PDIAG STDC DSTDC REV JR"
).split()
WINDOWS = {
    "Reference": ("2026-09-23", "2026-10-21"),
    "Later": ("2026-10-21", "2026-11-04"),
}
IST = timezone(timedelta(hours=5, minutes=30))
WAIT_MS = 15 * 60000
COST = 0.0003
BASE_EQUITY = 10000
UNIT = {"BTC": 0.1, "ETH": 1.0}


def epoch(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=IST).timestamp() * 1000)


def sign(side):
    assert side in ("buy", "sell"), side
    return 1 if side == "buy" else -1


def load(work):
    manifest = json.loads((work / "manifest.json").read_bytes())
    dates = defaultdict(list)
    book = defaultdict(list)
    seen = set()
    for item in manifest:
        file = work / item["file"]
        currency, kind1, _kind2, first, end = (
            file.stem.replace("option_combo", "option-combo")
            .replace("future_combo", "future-combo")
            .split("-")
        )
        dates[currency, kind1].append((int(first), int(end)))
        data = file.read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"], file
        page = json.loads(data)
        assert not page["has_more"] and len(page["trades"]) == item["trades"], file
        for trade in page["trades"]:
            coin, code, *_ = trade["instrument_name"].split("-")
            entry = (coin, trade["trade_id"])
            assert coin == currency and entry not in seen, entry
            seen.add(entry)
            book[coin, code].append(trade)
    assert len(dates) == 4
    for spans in dates.values():
        spans.sort()
        assert spans[0][0] == epoch(WINDOWS["Reference"][0])
        assert spans[-1][1] == epoch(WINDOWS["Later"][1])
        assert all(a[1] == b[0] for a, b in zip(spans, spans[1:])), spans[:3]
    for series in book.values():
        series.sort(
            key=lambda x: (x["timestamp"], int(x["trade_id"].rsplit("-", 1)[-1]))
        )
    return book, manifest


def legs(row):
    return {leg["instrument_name"]: leg for leg in row["legs"]}


def valid(row, qty, future):
    try:
        if row["amount"] < qty or row["index_price"] <= 0 or len(row["legs"]) < 2:
            return False
        if any(
            x["combo_id"] != row["instrument_name"]
            or x["combo_trade_id"] != row["trade_id"]
            or x["timestamp"] != row["timestamp"]
            or x["amount"] <= 0
            or x["price"] <= 0
            for x in row["legs"]
        ):
            return False
        if future and any("PERPETUAL" in x for x in legs(row)):
            return False
        weights = sum(
            sign(x["direction"]) * x["amount"] * x["price"] for x in row["legs"]
        )
        target = row["price"] * row["amount"] * sign(row["direction"])
        tick = 0.5 if future else 0.0001
        return abs(weights - target) <= tick * row["amount"] / 2 + 1e-10
    except (KeyError, TypeError):
        return False


def pnl(entry, exit, qty, future):
    a, b = legs(entry), legs(exit)
    assert a.keys() == b.keys()
    settlement = exit["index_price"]
    gross = fees = execution = 0.0
    for name, open_leg in a.items():
        close_leg = b[name]
        weight = open_leg["amount"] / entry["amount"]
        assert math.isclose(weight, close_leg["amount"] / exit["amount"])
        assert sign(open_leg["direction"]) == -sign(close_leg["direction"])
        amount = qty * weight
        start, end = open_leg["price"], close_leg["price"]
        if future:
            gross += (
                sign(open_leg["direction"])
                * amount
                * (1 / start - 1 / end)
                * settlement
            )
            fees += 0.0005 * amount * (1 / start + 1 / end) * settlement
            execution += COST * amount * (1 / start + 1 / end) * settlement
        else:
            gross += sign(open_leg["direction"]) * amount * (end - start) * settlement
            fees += (
                amount
                * (min(0.0003, start * 0.125) + min(0.0003, end * 0.125))
                * settlement
            )
            execution += COST * amount * (start + end) * settlement
    return gross, gross - fees, gross - fees - execution


def run(series, code, coin, dates):
    first, end = map(epoch, dates)
    future = code == "FS"
    qty = 100 if future else UNIT[coin]
    active = {}
    trades = []
    observed = eligible = 0
    for row in series:
        t = row["timestamp"]
        if not first <= t < end:
            continue
        observed += 1
        if not valid(row, qty, future):
            continue
        eligible += 1
        instrument = row["instrument_name"]
        entry = active.get(instrument)
        if entry is None and row["direction"] == "buy" and t + WAIT_MS < end:
            active[instrument] = row
        elif (
            entry is not None
            and row["direction"] == "sell"
            and t >= entry["timestamp"] + WAIT_MS
        ):
            trades.append(
                (t, *pnl(entry, row, qty, future), entry["trade_id"], row["trade_id"])
            )
            del active[instrument]
    return trades, len(active), observed, eligible


def summary(id_, item, coin, period, trades, unsettled):
    total = [0.0] * 3
    peaks = [BASE_EQUITY] * 3
    dds = [0.0] * 3
    fractions = [0.0] * 3
    wins = [0] * 3
    for trade in sorted(trades):
        for k, delta in enumerate(trade[1:4]):
            wins[k] += delta > 1e-9
            total[k] += delta
            equity = BASE_EQUITY + total[k]
            peaks[k] = max(peaks[k], equity)
            dds[k] = max(dds[k], peaks[k] - equity)
            fractions[k] = max(fractions[k], (peaks[k] - equity) / peaks[k])
    return dict(
        id=id_,
        name=item["name"],
        source=item["source_url"],
        period=period,
        group="Deribit combo trade-print model",
        market=coin,
        interval="Event",
        archive_interval="Trade prints",
        exit="First same combo sell print after 15 min",
        venue="Deribit",
        currency="USD",
        trades=len(trades),
        unsettled=unsettled,
        gross=total[0],
        after_fees=total[1],
        net=total[2],
        fees=total[0] - total[1],
        execution=total[1] - total[2],
        gross_wins=wins[0],
        fee_wins=wins[1],
        net_wins=wins[2],
        gross_dd=dds[0],
        fee_dd=dds[1],
        net_dd=dds[2],
        gross_dd_pct=fractions[0],
        fee_dd_pct=fractions[1],
        net_dd_pct=fractions[2],
    )


def replay(work):
    with (
        Path(__file__)
        .with_name("public-strategy-catalogue.csv")
        .open(encoding="utf-8-sig") as stream
    ):
        stock = list(csv.DictReader(stream))
    book, inputs = load(work)
    cases = []
    for id_, code in enumerate(STRUCTURES, 6054):
        item = stock[id_ - 1]
        assert item["source"] == "Deribit"
        windows = {
            (label, coin): run(book[coin, code], code, coin, dates)
            for label, dates in WINDOWS.items()
            for coin in UNIT
        }
        observed = sum(a[2] for a in windows.values())
        eligible = sum(a[3] for a in windows.values())
        closed = sum(len(a[0]) for a in windows.values())
        exposure = {
            f"{label}/{coin}": dict(
                observed=a[2], eligible=a[3], closed=len(a[0]), open=a[1]
            )
            for (label, coin), a in windows.items()
        }
        if closed == 0:
            cases.append(
                dict(
                    id=id_,
                    reason=f"Deribit {code}: {observed} observed, {eligible} size-eligible combo prints and no matched round trip",
                    evidence=exposure,
                )
            )
            continue
        rows = []
        ledger = {}
        for label in WINDOWS:
            btc, eth = windows[label, "BTC"], windows[label, "ETH"]
            rows.extend(
                [
                    summary(id_, item, "BTC combo", label, btc[0], btc[1]),
                    summary(id_, item, "ETH combo", label, eth[0], eth[1]),
                    summary(
                        id_,
                        item,
                        "BTC + ETH combo",
                        label,
                        btc[0] + eth[0],
                        btc[1] + eth[1],
                    ),
                ]
            )
            ledger[label] = {
                coin: [v[4:] for v in windows[label, coin][0]] for coin in UNIT
            }
        cases.append(dict(id=id_, results=rows, evidence=exposure, trade_ids=ledger))
    return dict(cases=cases, inputs=inputs)


if __name__ == "__main__":
    result = replay(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(
        json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        Counter(
            "closed replay" if x.get("results") else "insufficient round trips"
            for x in result["cases"]
        )
    )
