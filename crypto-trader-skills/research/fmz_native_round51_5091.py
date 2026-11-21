"""Check persistent native #5091 receipts against the recorded spot feeds."""
import gzip
import hashlib
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

D = Decimal
DATES = ("2026-10-01", "2026-11-19")
SYMBOLS = ("BTC_USDT", "ETH_USDT")
SOURCE = "https://www.fmz.com/strategy/354232"
LOADER = "836dcbb307e38d64cb99c7de53733e07c4fa8319fc1d3be9e48583929e1e1208"
RUNTIME = "504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0"


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()), parse_float=D)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wallet(snapshot, symbol):
    state = next(account for account in snapshot[1] if account["BaseCurrency"] == symbol)
    assets = {a["Currency"]: a for a in state["Assets"]}

    def amount(currency):
        row = assets.get(currency, {})
        return D(row.get("Amount", 0)) + D(row.get("FrozenAmount", 0))

    return amount(symbol), amount("USDT"), D(assets["USDT"]["Commission"]), state


def settlement(receipt, symbol):
    result = receipt["native_summary"]
    base, cash, fees, state = wallet(result["Snapshots"][-1], symbol)
    key = symbol + "_USDT"
    orders = [row for row in receipt["trail"] if row[0] == key]
    admitted = {row[4]: row[1] for row in orders if row[1] in ("Buy", "Sell") and row[4]}
    canceled = {row[3][0] for row in orders if row[1] == "CancelOrder" and row[4]}
    assert canceled <= admitted.keys()
    closed = [
        row[3] for row in receipt["author_endpoint_reads"]
        if row[0] == key and row[1] == "order" and row[3]["Status"] == 1
    ]
    assert len({trade["Id"] for trade in closed}) == len(closed)
    assert sorted(trade["Id"] for trade in closed) == sorted(
        oid for oid, side in admitted.items() if side == "Sell" and oid not in canceled
    )
    assert all(D(a["FrozenAmount"]) == 0 for a in state["Assets"])
    symbol_state = state["Symbols"][key]["TradeStatus"]
    assert sum((D(x["DealAmount"]) for x in closed), D(0)) == D(symbol_state["SellDealAmount"])
    assert sum(side == "Buy" for side in admitted.values()) == symbol_state["BuyOrderCount"]
    assert sum(side == "Sell" for side in admitted.values()) == symbol_state["SellOrderCount"]
    buys = sum(side == "Buy" and oid not in canceled for oid, side in admitted.items())
    assert D(buys) * D(".001") == D(symbol_state["BuyDealAmount"])
    initial_base = D(0 if symbol == "BTC" else 3)
    assert base == initial_base + D(symbol_state["BuyDealAmount"]) - D(symbol_state["SellDealAmount"])
    rejected = sum(row[1] == "Buy" and not row[4] for row in orders)
    min_errors = [entry[7] for entry in result["RuntimeLogs"] if entry[2] == 3]
    if symbol == "ETH":
        assert sum("ETH_USDT" in s and "below minimum 5" in s for s in min_errors) == rejected
    else:
        assert rejected == 0
    return {
        "accepted_buys": symbol_state["BuyOrderCount"],
        "buy_fills": buys,
        "canceled_orders": len(canceled),
        "rejected_buys": rejected,
        "closing_sales": closed,
        "base_at_end": str(base),
        "quote_at_end": str(cash),
        "native_fees": str(fees),
    }


def market_event_matches(tape, begin, left, right, price):
    scaled = int(price * 100)
    return [
        t - begin for t, asks, bids, close, _, _, _ in tape
        if left <= t - begin <= right
        and (close == scaled or any(level[0] == scaled for level in asks + bids))
    ]


def verify_basis(prefix, full, feed):
    early_end = prefix["last"]
    for key in ("trail", "author_endpoint_reads"):
        assert [v for v in prefix[key] if v[2] < early_end] == [
            v for v in full[key] if v[2] < early_end
        ]
    t0 = prefix["opening"]
    shifts = []
    previous = (D(0), D(10000))
    for snapshot in prefix["native_summary"]["Snapshots"]:
        base, cash, fees, _ = wallet(snapshot, "BTC")
        assert fees == 0
        change = (base, cash)
        if change == previous:
            continue
        if len(shifts) == 3:
            break
        assert base - previous[0] == D(".001")
        shifts.append((snapshot[0] - t0, (previous[1] - cash) * 1000))
        previous = change
    assert shifts == [(900, D("63936.25")), (1100, D("63942.81")), (1300, D("63942.81"))]
    btc = feed["feeds"]["BTC_USDT"]["data"]
    first = market_event_matches(btc, t0, 600, 900, shifts[0][1])
    second = market_event_matches(btc, t0, 900, 1300, shifts[1][1])
    assert first and second
    eth = feed["feeds"]["ETH_USDT"]["data"]
    before = [row for row in eth if row[0] < t0 and row[2]][-1]
    eth_start = D(before[2][0][0]) / 100
    assert eth_start == D("1807.33") and t0 - before[0] <= 1000
    return shifts, before[0], eth_start


def dollars(value):
    return float(value)


def metrics(symbol, date, start, gross, fee, trades, remaining):
    net = gross - fee
    gross_dd, net_dd = max(D(0), -gross), max(D(0), -net)
    def wins(value):
        return int(trades > 0 and value > 0)
    return {
        "id": 5091,
        "name": "LeeksReaper multi-asset Python",
        "market": symbol + "USDT spot",
        "source": SOURCE,
        "period": date + " 12:00–12:20 UTC",
        "interval": "Recorded FMZ Binance spot book and trade events",
        "quote_currency": "USDT",
        "currency_decimal_places": 8,
        "starting_equity": dollars(start),
        "gross": dollars(gross),
        "fees": dollars(fee),
        "after_fees": dollars(net),
        "execution": 0,
        "funding": 0,
        "net": dollars(net),
        "gross_dd": dollars(gross_dd),
        "gross_dd_pct": dollars(gross_dd / start),
        "fee_dd": dollars(net_dd),
        "fee_dd_pct": dollars(net_dd / start),
        "net_dd": dollars(net_dd),
        "net_dd_pct": dollars(net_dd / start),
        "gross_wins": wins(gross),
        "fee_wins": wins(net),
        "net_wins": wins(net),
        "trades": trades,
        "unsettled": remaining,
    }


def main(scratch, output):
    assert digest(scratch / "official_fmz_python.py") == LOADER
    assert digest(scratch / "depends/backtest_py_windows_64bit.so") == RUNTIME
    isolation = json.loads((scratch / "round3-isolation-python.json").read_bytes())
    assert isolation["file_error"][0] == isolation["network_error"][0] == "PermissionError"
    receipts = {date: read(scratch / f"r49-5091-{date}-audit.gz") for date in DATES}
    prefix = read(scratch / "r49-5091-2026-11-19-prefix-77.gz")
    assert prefix["last"] - prefix["opening"] == 77_000
    feeds = {date: read(scratch / f"r47-5091-{date}-feed.gz") for date in DATES}
    shifts, eth_open_time, eth_start = verify_basis(prefix, receipts[DATES[1]], feeds[DATES[1]])
    output_cases, results = [], []
    for date, receipt in receipts.items():
        assert receipt["native_hash"] == RUNTIME
        assert receipt["loader_hash"] == LOADER
        assert receipt["source_digest"] == feeds[date]["raw_document_sha256"]
        assert receipt["actual_feed"] == feeds[date]["proof"]
        assert receipt["outcome"] == "native end of backtest" and not receipt["err"]
        result = receipt["native_summary"]
        assert result["Finished"] and result["Progress"] == 100
        assert receipt["last"] - receipt["opening"] == 1_200_000
        assert all(req["period"] == ["1000"] and req["depth"] == ["5"] for req in receipt["requests"])
        assert all(D(e["FeeTaker"]) == D(0 if i == 0 else 200) for i, e in enumerate(receipt["task"]["Exchanges"]))
        assert all(receipt["counts"][key + ":GetDepth"] > 0 and receipt["counts"][key + ":GetTrades"] > 0 for key in SYMBOLS)
        for key in SYMBOLS:
            symbol = key.split("_")[0]
            proof = settlement(receipt, symbol)
            gross = fee = D(0)
            remaining = proof["buy_fills"] if symbol == "BTC" else 1
            trades = len(proof["closing_sales"])
            start = D(10000)
            if symbol == "ETH":
                bbo = [r for r in feeds[date]["feeds"][key]["data"] if r[0] < receipt["opening"] and r[2]][-1]
                start += 3 * D(bbo[2][0][0]) / 100
            if trades:
                assert date == DATES[1] and trades == 1
                (sale,) = proof["closing_sales"]
                price, size = D(sale["AvgPrice"]), D(sale["DealAmount"])
                tape = feeds[date]["feeds"][key]["data"]
                left = sale["Time"] - receipt["opening"] - 200
                hits = market_event_matches(tape, receipt["opening"], left, left + 800, price)
                assert hits
                if symbol == "BTC":
                    assert size == D(".00243")
                    basis = sum((p * q for (_, p), q in zip(shifts, (D(".001"), D(".001"), D(".00043")), strict=True)), D(0))
                    remaining -= 2
                else:
                    assert size == D("1.728")
                    basis = eth_start * size
                    fee = D(proof["native_fees"])
                    assert fee == price * size * D(".0002")
                    assert D(proof["quote_at_end"]) == D(10000) + price * size - fee
                gross = price * size - basis
                proof.update({"fifo_basis": str(basis), "source_price_confirmation_offsets_ms": hits, "closed_gross": str(gross), "closed_after_fees": str(gross - fee)})
            assert D(proof["native_fees"]) == fee
            proof["closing_sales"] = [{k: str(v) if isinstance(v, D) else v for k, v in row.items()} for row in proof["closing_sales"]]
            recorded_feed = dict(receipt["actual_feed"][key])
            recorded_feed["downloads"] = [
                {name: value for name, value in item.items() if name != "bytes"}
                for item in recorded_feed["downloads"]
            ]
            output_cases.append({"date": date, "symbol": symbol, "recorded_feed": recorded_feed, "checks": proof})
            results.append(metrics(symbol, date, start, gross, fee, trades, remaining))
    assert [r["trades"] for r in results] == [0, 0, 1, 1] and sum(r["net_wins"] for r in results) == 0
    report = {
        "schema": "FMZ #5091 native real-book archived alternate sessions",
        "pinned_source_sha256": receipts[DATES[0]]["source_digest"],
        "runtime_sha256": RUNTIME,
        "loader_sha256": LOADER,
        "isolation": isolation,
        "source_parameters": {k: str(v) if isinstance(v, D) else v for k, v in receipts[DATES[0]]["effective_parameters"].items()},
        "verification": {"source_reads_and_orders_equal_in_77_second_prefix": True, "first_btc_buy_lots": [[t, str(p)] for t, p in shifts], "eth_pre_start_bid": str(eth_start), "eth_pre_start_bid_ms": eth_open_time},
        "coverage": [[5091, "Tested - Native recorded spot events on two alternative dates", "The pinned source ran four BTC/ETH spot cases with recorded book and trade-print events. Original March 2022 snapshots are unavailable. Two scopes have no closes. The other two contain exact FIFO and fee-reconciled exits."]],
        "cases": output_cases,
        "results": results,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
