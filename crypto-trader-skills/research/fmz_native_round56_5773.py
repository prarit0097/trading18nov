"""Verify literal and compatible #5773 receipts on the recorded tape."""

import gzip
import json
import sys
from decimal import Decimal
from pathlib import Path

D = Decimal
SOURCE = "https://www.fmz.com/strategy/260806"


def main(scratch, output):
    job = json.loads(gzip.decompress((scratch / "r50-5773-pilot-input.json.gz").read_bytes()), parse_float=D)
    literal, display, compatible = [
        json.loads((scratch / f"r50-5773-{mode}.json").read_bytes(), parse_float=D)
        for mode in ("literal", "display", "compatibility")
    ]
    assert literal["engine"] == display["engine"] == compatible["engine"]
    assert literal["source"] == display["source"] == compatible["source"] == job["document_sha256"]
    source = job["source"]
    assert source.count("account.Info.totalWalletBalance") == 1
    assert "LogProfit(parseFloat(account.Info.totalWalletBalance), account)" in source
    assert set(line.split("_.")[1].split("(")[0] for line in source.splitlines() if "_." in line) == {"reduce", "max", "min"}
    start, end = job["start"] * 1000, job["end"] * 1000
    cases, rows = [], []
    for exact, shown, case in zip(literal["cases"], display["cases"], compatible["cases"], strict=True):
        coin = case["coin"]
        assert coin == exact["coin"] == shown["coin"]
        assert "reading 'totalWalletBalance'" in exact["outcome"] and exact["sourceTime"] == start + 200
        assert set(exact["counts"]) == {"SetContractType", "GetAccount"}
        assert "_ is not defined" in shown["outcome"] and shown["sourceTime"] == start + 900
        assert next(x for x in shown["trail"] if x["name"] == "GetTrades")["result"] == 500
        assert case["outcome"] == "native end of backtest" and case["sourceTime"] == end
        assert all(case["helperChecks"][key] > 0 for key in ("reduce", "max", "min"))
        assert case["summary"]["Finished"] and case["summary"]["Progress"] == 100
        market = job["feeds"][coin]
        tape = market["data"]
        denominator = 10 ** market["detail"]["quotePrecision"]
        sales = [x for x in case["trail"] if x["name"] == "Sell"]
        cancels = {x["args"][0]: x for x in case["trail"] if x["name"] == "CancelOrder"}
        assert len(sales) == (1 if coin == "BTC" else 2) == len(cancels)
        assert case["counts"].get("Buy", 0) == 0
        account_reads = [x["result"] for x in case["trail"] if x["name"] == "GetAccount"]
        assert len(account_reads) == case["counts"]["GetAccount"]
        assert all(x["Balance"] == x["Equity"] == 10000 and x["FrozenBalance"] == x["UPnL"] == 0 for x in account_reads)
        final = case["summary"]["Snapshots"][-1][1][0]
        assert final["PnL"] == final["Utilization"] == 0
        final_symbol = final["Symbols"][coin + "_USDT.swap"]["TradeStatus"]
        assert final_symbol["SellOrderCount"] == len(sales)
        assert final_symbol["BuyDealAmount"] == final_symbol["SellDealAmount"] == 0
        assert all(x["Currency"] == "USDT" and x["Amount"] == 10000 and x["Commission"] == x["Funding"] == 0 for x in final["Assets"])
        order_checks = []
        for sale in sales:
            limit, size = sale["args"]
            assert size == D(".03")
            cancel = cancels[sale["result"]]
            assert cancel["result"] is True
            left, right = sale["t"] - 200, cancel["t"] + 200
            prior = [event for event in tape if event[0] < left and event[2]][-1]
            assert left - prior[0] <= 1000
            records = [prior] + [event for event in tape if left <= event[0] <= right]
            max_bid = max(D(event[2][0][0]) / denominator for event in records if event[2])
            max_print = max(D(trade[2]) / denominator for event in records for trade in event[6] if left <= trade[0] <= right)
            assert max(max_bid, max_print) < limit
            order_checks.append({"id": sale["result"], "submit_ms": sale["t"], "cancel_ms": cancel["t"],
                                 "limit": str(limit), "max_recorded_bid": str(max_bid), "max_recorded_print": str(max_print),
                                 "tape_events_checked": len(records)})
        cases.append({"coin": coin, "exact_abort_ms_after_start": 200, "reporting_only_missing_helper_ms": 900,
                      "recorded_input": job["witness"][coin], "in_window_events": sum(start <= r[0] < end for r in tape),
                      "native_api_calls": case["counts"], "array_helper_domain_checks": case["helperChecks"],
                      "unfilled_order_proofs": order_checks})
        rows.append({"id": 5773, "name": "Modified LeeksReaper", "source": SOURCE, "market": coin + "USDT perpetual",
                     "group": "Flat short-window compatibility", "period": "2026-11-19 12:00:00–12:01:00 UTC",
                     "interval": "Native recorded Binance book and trade events", "quote_currency": "USDT",
                     "exit": "Source canceled its passive short entries. No order filled.", "starting_equity": 10000,
                     "trades": 0, "gross": 0, "fees": 0, "after_fees": 0, "net": 0, "execution": 0, "funding": 0,
                     "gross_dd": 0, "fee_dd": 0, "net_dd": 0, "gross_dd_pct": 0, "fee_dd_pct": 0, "net_dd_pct": 0,
                     "gross_wins": 0, "fee_wins": 0, "net_wins": 0, "unsettled": 0})
    report = {"schema": "FMZ #5773 short flat compatibility", "source_sha256": job["document_sha256"],
              "runtime_loader_sha256": literal["engine"], "source_code_sha256": job["source_sha256"],
              "coverage": [[5773, "Tested - short flat recorded futures compatibility", "Literal startup fails on an absent reporting field. A reporting-only adaptation and domain-verified Underscore helpers complete both fixed 60-second BTC/ETH scopes. All three passive sells were canceled without fills. The actual tape independently stays below all three limits. Filled-position behavior remains unverified."]],
              "cases": cases, "results": rows}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
