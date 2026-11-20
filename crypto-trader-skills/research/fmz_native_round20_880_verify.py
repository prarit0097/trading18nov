"""Independently reconcile the two complete BitMEX inverse SAR source replays."""

import argparse
import gzip
import hashlib
import json
from decimal import Decimal, localcontext
from pathlib import Path


D = Decimal
POSITION = D("10000")
STARTING_WALLET = D("2")
TAKER_FEE = D("0.00075")
EPS = D("0.00000000000001")
SATOSHI = D("0.00000001")
WORKER = "fmz_native_round20_880_worker.cjs"
CAPTURE = "fmz_native_round20_880_capture.py"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def check(actual, expected):
    assert abs(D(str(actual)) - expected) <= EPS, (actual, expected)


def drawdown(path):
    peak = STARTING_WALLET
    absolute = ratio = D(0)
    for value in path:
        peak = max(peak, value)
        absolute = max(absolute, peak - value)
        ratio = max(ratio, (peak - value) / peak)
    return {"BTC": str(absolute), "fraction": str(ratio)}


def verify(author, spec, replay):
    assert replay["counts"] == {"ticker":5761,"records":5762,"indicator":5760,"account":2}
    assert replay["max_warm_error"] == 0
    assert replay["start"] == spec["begin"] and replay["end"] == spec["end"]
    assert replay["max_number_records"] == replay["available_completed_bars"] + 1
    assert replay["available_completed_bars"] >= 500
    [order] = replay["orders"]
    [funding] = replay["funding"]
    first = spec["samples"][0]
    last = spec["samples"][-1]
    assert order["at"] == first[0] and order["side"] == 1 and order["direction"] == "buy"
    assert D(order["qty"]) == D(replay["position"]) == POSITION
    assert order["quote_local_us"] == first[7] and order["quote_exchange_us"] == first[8]
    assert 0 <= first[0] * 1_000_000 - first[7] <= 5_000_000
    assert order["price"] == first[10] and first[12] >= POSITION
    assert order["observed_top_size"] == first[12] and order["last"] == first[6]
    execution_price = D(str(order["price"]))
    fee = POSITION / execution_price * TAKER_FEE
    assert STARTING_WALLET > POSITION / execution_price + 2 * fee
    check(order["cash"], STARTING_WALLET - fee)
    check(order["fee"], fee)
    assert funding["at"] == spec["today"] + 4*3600 and D(funding["qty"]) == POSITION
    rate = D(str(funding["rate"]))
    assert rate == D("0.0001") and str(rate) == funding["before"][6]
    funded = -POSITION / D(str(funding["mark"])) * rate
    alternative = -POSITION / D(str(funding["alternative_mark"])) * rate
    check(funding["amount"], funded)
    check(funding["alternative_amount"], alternative)
    assert abs(funded-alternative) < 2 * SATOSHI
    before = funding["before"]
    rolled = funding["first_rolled"]
    assert before in spec["funding_near_settlement"] and rolled in spec["funding_near_settlement"]
    assert before[5] == funding["at"]*1_000_000 < rolled[5]
    assert before[2] == funding["mark"] and rolled[2] == funding["alternative_mark"]

    assert len(spec["samples"]) == len(replay["path"]) == 5761
    assert [r[0] for r in spec["samples"]] == list(range(spec["begin"],spec["end"]+1,5))
    day_low = min(row[5] for row in spec["samples"])
    assert day_low >= spec["daily_exchange"][2]
    highest_sar = max(row[7] for row in replay["path"])
    assert spec["daily_exchange"][2] > highest_sar, "Observed full-day price lows admit an exit"
    matching = [r for r in spec["daily_fmz_near"] if r[0] == spec["today"] + 86400]
    assert len(matching) == 1 and matching[0][1:5] == spec["daily_exchange"]
    gross_curve, fee_curve, net_curve = [], [], []
    lowest_excess = None
    for point, sample in zip(replay["path"], spec["samples"], strict=True):
        timestamp, qty, basis, cash, unrealized, mark, last_price, _ = point
        assert timestamp == sample[0] and mark == sample[15] and last_price == sample[6]
        assert D(qty) == POSITION and D(str(basis)) == execution_price
        mark = D(str(mark))
        carry = funded if timestamp >= funding["at"] else D(0)
        theoretical_unrealized = POSITION * (1/execution_price - 1/mark)
        theoretical_cash = STARTING_WALLET - fee + carry
        check(cash, theoretical_cash)
        check(unrealized, theoretical_unrealized)
        gross_equity = STARTING_WALLET + theoretical_unrealized
        gross_curve.append(gross_equity)
        fee_curve.append(gross_equity-fee)
        net_curve.append(gross_equity-fee+carry)
        maintenance_and_exit_fee = POSITION / mark * (D("0.005") + TAKER_FEE)
        excess = net_curve[-1] - maintenance_and_exit_fee
        lowest_excess = excess if lowest_excess is None else min(lowest_excess,excess)
    assert lowest_excess > D("1")
    assert replay["ending_mark"] == last[15]
    check(replay["cash"], STARTING_WALLET - fee + funded)
    check(replay["ending_unrealized"], gross_curve[-1] - STARTING_WALLET)
    price_cost = POSITION * (1/D(str(first[6]))-1/execution_price)
    assert price_cost >= 0
    diagnostics = {
        "day": replay["day"],
        "daily_warmup_closed_bars": replay["available_completed_bars"],
        "closed_day_alignment": "FMZ 1d labels are right endpoints in both crosschecked dates.",
        "observed_trigger_count": replay["counts"]["indicator"],
        "lowest_full_day_trade_price": spec["daily_exchange"][2],
        "highest_native_SAR": highest_sar,
        "order": order,
        "funding": funding,
        "funding_mark_sensitivity_BTC":str(abs(funded-alternative)),
        "max_rounding_sensitivity_BTC":"0.00000002",
        "wallet_change_BTC": str(funded-fee),
        "gross_marked_pnl_BTC": str(gross_curve[-1]-STARTING_WALLET),
        "after_fee_marked_pnl_BTC": str(fee_curve[-1]-STARTING_WALLET),
        "net_marked_pnl_BTC": str(net_curve[-1]-STARTING_WALLET),
        "observed_opening_execution_vs_last_BTC": str(price_cost),
        "mark_to_market_drawdown": {
            "gross":drawdown(gross_curve),
            "after_fees":drawdown(fee_curve),
            "net":drawdown(net_curve),
        },
        "lowest_equity_above_maintenance_and_exit_fee_BTC":str(lowest_excess),
        "ending_mark": replay["ending_mark"],
        "capture_references": spec["captures"],
        "fmz_history_references": spec["fmz_history_references"],
    }
    result = {
        "id":880, "market":"XBTUSD perpetual [BTC settlement]",
        "group":"FMZ Native · BitMEX inverse SAR", "name":author["name"],
        "source":author["archive_url"], "period":replay["day"]+" 02:00–10:00 UTC",
        "exit":"Archived SAR, position carried at window end", "interval":"1d chart · 5s poll",
        "currency":"BTC","quote_currency":"BTC","currency_decimal_places":12,
        "trades":0,"unsettled":1,"gross_wins":0,"fee_wins":0,"net_wins":0,
        "gross":0,"after_fees":0,"net":0,"fees":0,"execution":0,"funding":0,
        "gross_dd":0,"fee_dd":0,"net_dd":0,"gross_dd_pct":0,"fee_dd_pct":0,"net_dd_pct":0,
        "starting_equity":float(STARTING_WALLET),
        "mark_to_market_net":float(net_curve[-1]-STARTING_WALLET),
        "remaining_unrealized":float(gross_curve[-1]-STARTING_WALLET),
    }
    return result, diagnostics


def assemble(staged, receipt, capture_file, worker_file):
    job_raw = staged.read_bytes()
    native_raw = receipt.read_bytes()
    job = json.loads(gzip.decompress(job_raw))
    native = json.loads(native_raw)
    assert sha(job_raw)==native["job_sha256"]
    assert sha(job["source"].encode())==job["source_sha256"]==native["source_sha256"]
    assert native["math_only_market_requests"]==0
    author=job["author"]
    assert author["archive_scope"]["args"] == '[["Amount",10000],["time_interval",86400]]'
    assert [r["day"] for r in native["scopes"]]==[t for t in job["scenarios"]]
    with localcontext() as ctx:
        ctx.prec=42
        records=[verify(author,job["scenarios"][r["day"]],r) for r in native["scopes"]]
    return {
        "coverage":[[880,"Tested · archived BitMEX inverse SAR on two exact source-date scopes",
          "The BTC-only published 10,000-contract 1x strategy ran with causal partial daily bars and native FMZ SAR. Two 8h slices each opened one long and closed zero. Independent accounting reconciled every observed mark, trading fee and selected funding mark. Realized win rate is undefined. Marked BTC P&L and drawdowns are reported separately."]],
        "results":[row for row,_ in records],
        "diagnostics":[row for _,row in records],
        "win_rate":None,
        "source":author,
        "inputs":{"job_sha256":sha(job_raw),"native_receipt_sha256":sha(native_raw),
                  "fmz_math_engine_sha256":native["native_engine_sha256"],
                  "capture_script":CAPTURE,"capture_script_sha256":sha(capture_file.read_bytes()),
                  "worker_script":WORKER,"worker_script_sha256":sha(worker_file.read_bytes())},
        "implementation": {
            "periods":"Two free first-of-month windows inside the author's source date range were declared before replay. Each starts flat with 2 BTC virtual collateral. The original source named BitMEX XBT/USD and gave no explicit wallet starting value.",
            "signal":"Archive quantity 10,000 inverse USD-face contracts, 1x, daily current bar and a 5s polling loop. The source uses FMZ's own WASM TA-Lib SAR implementation. Recalculate using previous closed daily FMZ bars and only market trades observable at each simulated decision time. All lookback checks from 100 through all available closed bars agree.",
            "host_feed":"The archived XBTUSD branch used native GetCurrency XBT_USD. Public FMZ daily XBT_USD.swap finished-candle OHLC matches each Tardis day exactly when the reported FMZ timestamp is interpreted as the UTC right endpoint. Raw intraday Tardis trades supply current daily high, low and last. FMZ historical hourly bars are not used.",
            "fills":"The rule's limit equals the current observed best ask for a buy and bid for a sell. Require displayed size to cover the whole limit and a strictly causal quote at most five seconds old. The selected scenarios execute only one taker entry each and leave no resting orders. No synthetic end-of-window liquidation.",
            "settlement":"1 USD contract face and BTC inverse accounting. Debits use the 2020 base taker rate and the captured 04:00 UTC scheduled funding rate. The settlement calculation uses the last observed mark before the funding timestamp rolled. A second calculation with the first rolled mark quantifies mark timing sensitivity below two satoshi.",
            "drawdown":"Zero in the closed-trade results because both windows end with open positions. The marked curves record the five-second BTC equity drawdown before fees, after fees and after applied funding. Terminal unrealized P&L uses the latest mark observable before the fixed boundary.",
            "precision":"Independent Decimal math checks floating native receipts at 1e-14 BTC. Simulated per-event amounts use fractional satoshi precision. The receipt gives a two-satoshi envelope for two independent fee/funding rounding events.",
        },
        "reproduction":"Place the capture script in the existing research scratch directory alongside a JSON parameter-proof array containing this report source field. The capture script reads the pinned FMZ ZIP and retrievable public records and writes a compact gzip job into round3-native. Run the worker in that existing network-denied AppContainer. Pass the job, native receipt, capture script, worker script and fresh output path to the verifier.",
        "references":[
            "https://www.fmz.com/strategy/224799",
            "https://docs.tardis.dev/historical-data-details/bitmex",
            "https://www.bitmex.com/blog/why-we-revamped-our-fee-structure",
            "https://www.bitmex.com/blog/introducing-and-explaining-the-positive-impact-of-lower-maintenance-margins",
            "https://support.bitmex.com/hc/en-gb/articles/5903013223837-What-are-the-Trading-Fees-and-where-can-I-see-what-I-ve-paid",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("staged","receipt","capture","worker","out"):
        parser.add_argument(name,type=Path)
    opts=parser.parse_args()
    report=assemble(opts.staged,opts.receipt,opts.capture,opts.worker)
    with opts.out.open("x",encoding="utf-8",newline="\n") as output:
        output.write(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    for row in report["diagnostics"]:
        print(row["day"],row["net_marked_pnl_BTC"],row["mark_to_market_drawdown"]["net"])
