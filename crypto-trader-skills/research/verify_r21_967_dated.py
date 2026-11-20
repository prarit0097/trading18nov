"""Independently reconcile dated OKEX SuperTrend cold-start orders and equity."""

import argparse
import gzip
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path


D = Decimal
BALANCE = D(1)
FACE = D(100)
TAKER = D("0.0005")
MAKER = D("0.0002")
US = 1_000_000
EPS = D("0.00000000000001")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check(actual,expected):
    assert abs(D(str(actual))-expected)<=EPS,(actual,expected)


def dd(equity):
    peak=BALANCE
    dollar=rate=D(0)
    for x in equity:
        peak=max(peak,x)
        dollar=max(dollar,peak-x)
        rate=max(rate,(peak-x)/peak)
    return float(dollar),float(rate)


def passive_proof(order,micro):
    start=order["timestamp"]
    side=order["side"]
    limit=order["limit"]
    proof=order["passive"]
    assert order["cancel_at"]==proof["to"]==start+2
    if proof["conclusion"]=="no observable match in exact cancellation window":
        for sec in (start,start+1):
            for offset,trader,p,size in micro["tables"]["trades"].get(str(sec),[]):
                if sec==start and offset==0:
                    continue
                assert trader==side or (p>limit if side>0 else p<limit)
            for offset,bid,ask in micro["tables"]["quotes"].get(str(sec),[]):
                if sec==start and offset==0:
                    continue
                assert (ask>limit if side>0 else bid<limit)
        assert "price" not in order
        return False
    assert proof["conclusion"]=="strict through price" and proof["oneSecondBound"]
    ref=proof["firstTrade"]
    assert start*US<ref["t"]<(start+1)*US
    matches=[
        (sec*US+offset,p,qty)
        for sec in (start,start+1)
        for offset,taker,p,qty in micro["tables"]["trades"].get(str(sec),[])
        if (sec!=start or offset>0) and taker==-side and (p<limit if side>0 else p>limit) and qty>=1
    ]
    assert min(matches)==(ref["t"],ref["p"],ref["q"])
    assert order["fill_local_us"]==ref["t"] and order["price"]==limit
    return True


def verify(rec,tape,micro,author):
    assert "issue" not in rec and rec["begin"]==tape["start"] and rec["end"]==rec["finished_at"]==tape["end"]
    assert rec["counts"]["empty"]==1 and rec["counts"]["cancels"]==len(rec["orders"])
    assert tape["symbol"]=="BTC-USD-200327"
    assert tape["proof"]["trades"]["closed_interval_count"]==80
    assert tape["proof"]["derivative_ticker"]["funding_field_events"]==0
    assert len(rec["path"])==len(tape["data"]["quotes"])==72001
    executions={}
    orders=Counter()
    for order in rec["orders"]:
        sec=order["timestamp"]
        side=order["side"]
        assert order["qty"]==1 and order["cancel_at"]==sec+2 and sec>=rec["begin"]+45*15*60
        quote=tape["data"]["quotes"][sec-rec["begin"]]
        assert quote==order["quote"]
        seen,exchange,bid,ask,bid_size,ask_size=quote
        assert exchange<=sec*US and 0<=sec*US-seen<=2*US and bid<ask
        if "passive" in order:
            if not passive_proof(order,micro):
                orders["cancelled_no_observed_match"]+=1
                continue
            applied=sec+1
            rate=MAKER
            orders["maker"]+=1
        else:
            assert order["fill_local_us"]==sec*US
            if side>0:
                assert order["price"]==ask<=order["limit"] and ask_size>=1
            else:
                assert order["price"]==bid>=order["limit"] and bid_size>=1
            applied=sec
            rate=TAKER
            orders["taker"]+=1
        assert applied not in executions and D(str(order["feeRate"]))==rate
        executions[applied]=(order,rate)
    cash=BALANCE
    gross_total=pos=entry=entry_fee=D(0)
    profits=[];net_profits=[];settled=[]
    gross_marks=[];net_marks=[]
    for i,point in enumerate(rec["path"]):
        sec,actual_cash,actual_pos,actual_entry,mark,unreal=point
        assert sec==rec["begin"]+i
        native_mark=tape["data"]["derivative_ticker"][i]
        assert mark==(native_mark[2] if native_mark is not None else None)
        if sec in executions:
            o,rate=executions[sec]
            px=D(str(o["price"]))
            fee=FACE/px*rate
            check(o["fee"],fee)
            gross=D(0)
            if o["direction"] in ("buy","sell"):
                assert pos==0
                pos,entry,entry_fee=D(o["side"]),px,fee
            else:
                assert pos==-D(o["side"])
                gross=pos*FACE*(1/entry-1/px)
                profits.append(gross)
                net_profits.append(gross-entry_fee-fee)
                settled.append({"close_second":sec,"gross_BTC":str(gross),
                                "entry_and_exit_fees_BTC":str(entry_fee+fee),
                                "after_fees_BTC":str(net_profits[-1])})
                pos=entry=entry_fee=D(0)
            cash+=gross-fee
            gross_total+=gross
            check(o["gross"],gross)
            check(o["cash"],cash)
        assert D(str(actual_pos))==pos
        check(actual_entry,entry)
        check(actual_cash,cash)
        expected=pos*FACE*(1/entry-1/D(str(mark))) if pos else D(0)
        check(unreal,expected)
        gross_marks.append(BALANCE+gross_total+expected)
        net_marks.append(cash+expected)
    assert len(profits)==(1 if rec["day"]=="2020-02-01" else 2)
    assert all(x<0 for x in profits+net_profits)
    assert D(rec["pos"])==pos and pos!=0
    check(rec["cash"],cash)
    check(rec["entry"],entry)
    closed_gross=sum(profits)
    closed_net=sum(net_profits)
    gross_dd,gross_dd_pct=dd(BALANCE+sum(profits[:n]) for n in range(1,len(profits)+1))
    net_dd,net_dd_pct=dd(BALANCE+sum(net_profits[:n]) for n in range(1,len(net_profits)+1))
    result={
        "id":967,"name":author["name"],"group":"FMZ Native · OKEX dated inverse",
        "market":"BTC-USD-200327 [BTC settlement]","source":author["archive_url"],
        "period":rec["day"]+" 00:00–20:00 UTC","interval":"15m chart · cold-start",
        "exit":"Archived SuperTrend flip and two-second order lifetime",
        "currency":"BTC","quote_currency":"BTC","currency_decimal_places":12,"starting_equity":1,
        "trades":len(profits),"unsettled":1,"gross_wins":0,"fee_wins":0,"net_wins":0,
        "gross":float(closed_gross),"after_fees":float(closed_net),"net":float(closed_net),
        "fees":float(closed_gross-closed_net),"execution":0,"funding":0,
        "gross_dd":gross_dd,"fee_dd":net_dd,"net_dd":net_dd,
        "gross_dd_pct":gross_dd_pct,"fee_dd_pct":net_dd_pct,"net_dd_pct":net_dd_pct,
        "mark_to_market_net":float(net_marks[-1]-BALANCE),"remaining_unrealized":float(net_marks[-1]-cash),
    }
    proof={"day":rec["day"],"order_counts":dict(orders),"hours":20,"calls":rec["counts"],
           "closed":settled,"orders":rec["orders"],"capture":tape["proof"],"terminal_cash_BTC":str(cash),
           "open_qty":int(pos),"open_basis":str(entry),"terminal_mark":rec["path"][-1][4],
           "mark_to_market_drawdown":{"gross":dd(gross_marks),"net":dd(net_marks)}}
    return result,proof


def main(base_path,micro_path,receipt_path,out):
    base_raw=base_path.read_bytes()
    micro_raw=micro_path.read_bytes()
    receipt_raw=receipt_path.read_bytes()
    base=json.loads(gzip.decompress(base_raw))
    micro=json.loads(gzip.decompress(micro_raw))
    receipt=json.loads(receipt_raw)
    assert sha(base_raw)==micro["base_sha256"]==receipt["job_sha256"]
    assert sha(micro_raw)==receipt["micro_sha256"]
    assert sha(base["source"].encode())==receipt["source_sha256"]==base["source_sha256"]
    author=base["author"]
    assert author["args"]=={"Amount":1,"TradeInterval":2000,"PriceTick":0.5,"Symbol":"quarter","pd":45,"factor":3}
    assert [r["day"] for r in receipt["scopes"]]==["2020-02-01","2020-03-01"]
    rows=[verify(r,base["scopes"][r["day"]],micro["scopes"][r["day"]],author) for r in receipt["scopes"]]
    report={
        "coverage":[[967,"Tested · dated OKEX BTC quarter cold-start windows",
          "Both 20h cold-start trials completed on captured BTC-USD-200327. Exact archived source closed 1 and 2 losing trades and held one position in each. The one maker fill is bounded within one mark sample by strict trade-through. The author’s preceding lookback and full August 2019–March 2020 deployment interval remain untested."]],
        "results":[r for r,_ in rows],
        "source":author,
        "diagnostics":[p for _,p in rows],
        "receipts":{"base_sha256":sha(base_raw),"market_micro_sha256":sha(micro_raw),"native_sha256":sha(receipt_raw)},
        "scope":"First-of-month public capture dates (February 1 and March 1, 2020) inside the authored interval with exact dated quarter 200327. Each starts flat with 1 BTC at midnight UTC, begins with no preceding bars and grows trade-derived current/closed 15-minute records causally. This measures cold startup, separate from the publisher’s original multi-month warm state and FMZ fee/broker setup.",
        "market_proof":"The obsolete Futures_OKCoin endpoint returned HTTP 500. The available generic Futures_OKX BTC_USD.quarter endpoint emitted a February 1 first 15-minute high of 9460.3, against the exact dated contract’s 9624.94. That generic source was discarded. Direct captured trades, BBO and derivative marks share the same dated contract, with per-file SHA-256 and complete observed market updates.",
        "fill_model":"A limit already crossing the observed top is priced at the exact visible top with proof of size >=1. The source sleeps 2 seconds then cancels. A passive intent with neither eligible aggressive trade nor crossed quote in that interval remains unfilled in the observed-market model. A strict-through trade proves execution of the single maker contract at its limit. The March fill’s precise sub-second timestamp can vary between placement and the first through trade at +81.017 ms. The wallet path, source callback and mark samples are invariant across that entire interval.",
        "accounting":"The position price and P&L are inverse in BTC using $100 contract face. Actual gross uses modeled execution quotes including spread. Taker 0.05% and maker 0.02% are explicit benchmark rates from the published OKX tier example, separate from a verified individual 2020 fee schedule. The strategy has no exposure at the daily 08:00 UTC settlement, no expiry in the windows and no perpetual funding. No position is forced to close at the cutoff. Realized drawdown uses closed P&L, with a separate observed one-second marked drawdown.",
        "reproduction":"The read-only staged capture and limited-order evidence scripts write compact pinned tapes into round3-native. Run the exact source worker there under the existing network-denied AppContainer and call the Decimal verifier with the two gzip tapes and receipt. Copy the Round 20 capture script into the scratch directory as stage_r20_880_bitmex_sar.py for the shared stream hasher and OHLC accumulator, and preserve the R21 stage filenames in the same directory. All dependencies are open browser or local research evidence.",
        "references":[
            "https://www.fmz.com/strategy/201837",
            "https://www.fmz.com/bbs-topic/5438",
            "https://docs.tardis.dev/historical-data-details/okex-futures",
            "https://www.okx.com/en-us/help/expiry-futures",
            "https://www.okx.com/en-gb/help/launch-of-futures-contract-daily-settlement-and-adjustments-of-perpetual-swap-settlement-and-funding-time",
            "https://www.okx.com/help/how-to-calculate-the-contract-transaction-fee"
        ],
    }
    with out.open("x",encoding="utf-8",newline="\n") as f:f.write(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    for result,proof in rows:
        print(proof["day"],result["trades"],result["gross"],result["after_fees"],result["net_dd"],result["mark_to_market_net"],proof["mark_to_market_drawdown"])


if __name__=="__main__":
    a=argparse.ArgumentParser(description=__doc__)
    for name in ("base","micro","receipt","out"): a.add_argument(name,type=Path)
    opts=a.parse_args()
    main(opts.base,opts.micro,opts.receipt,opts.out)
