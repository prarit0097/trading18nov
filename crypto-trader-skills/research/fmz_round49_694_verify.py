"""Reconcile the authored BTC, ETH and LTC spot replay against the archived tapes."""

import gzip
import hashlib
import json
import sys
from collections import deque
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, sha256

BEGIN = 1550620800000
END = 1578614400000
MAKER, TAKER = Decimal("0.00015"), Decimal("0.00020")
BALANCE = Decimal(10000)
SYMBOLS = ("BTC_USDT", "ETH_USDT", "LTC_USDT")
INITIAL = (Decimal(3), Decimal(30), Decimal(100))


def exact(path):
    return json.loads(path.read_bytes(), parse_float=Decimal)


def check_fee_control(path, rate):
    control = exact(path)
    prices = []
    for symbol in SYMBOLS:
        for expected, item in zip(("Buy", "Sell"), control[symbol], strict=True):
            assert item["side"] == expected
            sign = 1 if expected == "Buy" else -1
            order = item["order"]
            before, after = item["before"], item["after"]
            amount, price = order["DealAmount"], order["AvgPrice"]
            notional = amount * price
            observed_fee = before["Balance"] - after["Balance"] - sign * notional
            assert order["Status"] == 1 and amount > 0
            assert abs(observed_fee - notional * rate) < Decimal("0.00000001")
            assert abs(after["Stocks"] - before["Stocks"] - sign * amount) < Decimal(
                "0.00000001"
            )
            if rate == MAKER:
                assert price == order["Price"]
            prices.append(
                [symbol, expected, str(price), str(amount), str(observed_fee)]
            )
    return prices


def reduce_inventory(lots, orders, price, stamp, quantity):
    remaining, basis, entry_fee = quantity, Decimal(0), Decimal(0)
    while remaining:
        lot_quantity, lot_price, rate = lots.popleft()
        used = min(lot_quantity, remaining)
        basis += used * lot_price
        entry_fee += used * lot_price * rate
        remaining -= used
        if used < lot_quantity:
            lots.appendleft((lot_quantity - used, lot_price, rate))
    gross = quantity * price - basis
    fee = entry_fee + quantity * price * MAKER
    orders.append(
        {
            "dir": 1,
            "qty": float(quantity),
            "entryPrice": float(basis / quantity),
            "exitPrice": float(price),
            "exitTime": stamp,
            "commission": float(fee),
            "profit": float(gross - fee),
        }
    )


def reconcile(symbol, initial, opening, closing, history, tape):
    scale = Decimal(10) ** tape["detail"]["quotePrecision"]
    rows = {r[0]: r for r in tape["data"]}
    start_mark = Decimal(rows[BEGIN][1]) / scale
    end_mark = Decimal(rows[END - 60000][4]) / scale
    assert start_mark == opening["ticker"]["Last"]
    assert (opening["account"]["Balance"], opening["account"]["Stocks"]) == (
        BALANCE,
        initial,
    )
    opening_equity = BALANCE + initial * start_mark
    cash, inventory = BALANCE, initial
    lots = deque([(initial, start_mark, Decimal(0))])
    trades = []
    submitted = filled = canceled = 0
    fee = Decimal(0)
    prior = BEGIN
    order_witnesses = []
    for order in history:
        stamp = order["Time"]
        assert (
            order["Id"] == submitted + 1
            and prior <= stamp < END
            and order["Symbol"] == symbol
        )
        submitted += 1
        prior = stamp
        quantity, price, side = order["DealAmount"], order["AvgPrice"], order["Type"]
        assert side in (0, 1)
        if order["Status"] == 2:
            assert quantity == price == 0
            canceled += 1
            continue
        assert (
            order["Status"] == 1
            and quantity == order["Amount"] > 0
            and price == order["Price"]
        )
        witness = rows[stamp // 60000 * 60000]
        assert witness[5] > 0 and witness[3] <= price * scale <= witness[2], order
        order_witnesses.append(
            [order["Id"], stamp, side, str(quantity), str(price), witness[0]]
        )
        total = price * quantity
        cash += -total if side == 0 else total
        fee += total * MAKER
        inventory += quantity if side == 0 else -quantity
        assert inventory >= 0
        if side == 0:
            lots.append((quantity, price, MAKER))
        else:
            reduce_inventory(lots, trades, price, stamp, quantity)
        filled += 1
    terminal = closing["account"]
    assert (
        terminal["FrozenBalance"] == terminal["FrozenStocks"] == 0
        and not closing["orders"]
    )
    assert prior < END - 300000
    assert abs(cash - fee - terminal["Balance"]) < Decimal("0.00000001")
    assert inventory == terminal["Stocks"] == sum(lot[0] for lot in lots)
    ending_equity = terminal["Balance"] + inventory * end_mark
    return {
        "asset": symbol,
        "trades": trades,
        "start_equity": float(opening_equity),
        "end_equity": float(ending_equity),
        "unsettled": int(inventory > 0),
        "cash": str(terminal["Balance"]),
        "inventory": str(inventory),
        "start_mark": str(start_mark),
        "end_mark": str(end_mark),
        "submitted": submitted,
        "filled": filled,
        "canceled": canceled,
        "all_fill_commissions": str(fee),
        "witnesses": order_witnesses,
    }


def main(tape_path, first, original, maker, taker, worker, prior, output):
    recorded, unmuted = exact(first), exact(original)
    assert recorded.keys() == unmuted.keys()
    compared = (
        "opening",
        "final",
        "order_histories",
        "sleep_calls",
        "clock_witness",
        "last_time",
        "source_cutoff",
        "readback_buffer_ms",
    )
    assert all(recorded[key] == unmuted[key] for key in compared)
    assert (
        BEGIN < unmuted["source_cutoff"] < END and END - unmuted["source_cutoff"] < 3000
    )
    staged = gzip.decompress(tape_path.read_bytes())
    market = json.loads(staged)
    receipt = exact(prior)
    assert (
        hashlib.sha256(staged).hexdigest()
        == "e6bada4aff24fe5d2a5a2073cb0a299329ce00b44056e80af19fb746931eaf78"
    )
    assert (
        sha256(prior)
        == "2e97a1dc85580462b248a3756554822365892c47042676e6d474a72c3c904493"
    )
    controls = {
        "maker": check_fee_control(maker, MAKER),
        "taker": check_fee_control(taker, TAKER),
    }
    cases = [
        reconcile(s, q, a, b, unmuted["order_histories"][s], market["feeds"][s])
        for s, q, a, b in zip(
            SYMBOLS, INITIAL, unmuted["opening"], unmuted["final"], strict=True
        )
    ]
    assert [c["filled"] for c in cases] == [159, 216, 278]
    results = []
    for selected in ([cases[0]], [cases[1]], [cases[2]], cases[:2], cases):
        equity = sum(c["start_equity"] for c in selected)
        events = [order for c in selected for order in c["trades"]]
        row = ledger_metrics(events, equity, sum(c["unsettled"] for c in selected))
        results.append(
            dict(
                id=694,
                group="FMZ Python / saved OKEX spot portfolio",
                market=" + ".join(c["asset"] for c in selected),
                period="2019-02-20 to 2020-01-10 UTC",
                interval="500 ms authored polling on native 1m feed",
                archive_interval="1m",
                order_family="Spot FIFO / timed passive orders",
                exit="Authored five-percent bands and FIFO sell lots",
                currency="USDT",
                funding=0.0,
                **row,
            )
        )
    for case in cases:
        case.pop("trades")
    result = {
        "schema": "FMZ native #694 archived three-market spot ledger",
        "scope": "Native source with saved instruments and wallet settings. Author sleep cadence and virtual time remain active. Market modeling uses minute-based simulated ticks, and FIFO sell reductions use the order placement timestamp for realized drawdown. Independent venue fill chronology within each minute is unavailable.",
        "source_url": receipt["archived_document"],
        "source_sha256": receipt["archived_sha256"],
        "proof": {
            name: sha256(path)
            for name, path in (
                ("input", tape_path),
                ("market_manifest", prior),
                ("control_replay", first),
                ("unmuted_replay", original),
                ("maker_control", maker),
                ("taker_control", taker),
                ("worker", worker),
            )
        },
        "staged_payload_sha256": hashlib.sha256(staged).hexdigest(),
        "native_comparison": {
            "matching_fields": compared,
            "polls": unmuted["sleep_calls"],
            "source_cutoff": unmuted["source_cutoff"],
            "readback_time": unmuted["last_time"],
        },
        "initial_inventory_valuation": "Native starting marks serve as the cost basis for seeded inventory. It incurs no fictional entry fee.",
        "fee_controls": controls,
        "cases": cases,
        "coverage": [
            [
                694,
                "Tested · saved native BTC/ETH/LTC spot portfolio",
                "The full authored spot window and all three starting books ran on the equivalent FMZ OKX adapter. Two native runs match order and financial state. Every filled limit has a positive-volume placement bar with a compatible price. FIFO wallet and fee checks agree.",
            ]
        ],
        "results": results,
    }
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
