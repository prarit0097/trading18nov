"""Reconcile #5510's authored ticker signals and spot rejection results."""

import argparse
import gzip
import hashlib
import json
from collections import deque
from decimal import Decimal
from pathlib import Path


D=Decimal
STEP=60000
LOOKBACK=1440
EXPECTED_HASH="be44e1fc60b138cd1ae07a4150361e1692685852e8860470a76f13cac3a378ab"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def extrema(prices):
    lo,hi=deque(),deque()
    lows=[]
    highs=[]
    for i,p in enumerate(prices):
        while lo and lo[0][0]<i-LOOKBACK:
            lo.popleft()
        while hi and hi[0][0]<i-LOOKBACK:
            hi.popleft()
        if i>=LOOKBACK:
            if p>hi[0][1]:highs.append(i)
            elif p<lo[0][1]:lows.append(i)
        while lo and lo[-1][1]>=p:
            lo.pop()
        while hi and hi[-1][1]<=p:
            hi.pop()
        lo.append((i,p))
        hi.append((i,p))
    return highs,lows


def verify(tape,trial,minimum,first,last):
    assert trial["boundary_ms"]==last
    cash=trial["balance"]
    assert trial["ending_cash"]==cash and trial["ending_stock"]==trial["frozen_quote"]==0
    assert trial["fees_collected"]==trial["fills"]==0
    values=[D(p) for p in tape["price"]]
    highs,lows=extrema(values)
    eligible=[n for n in highs if D(cash)>values[n]]
    expected={"ticker":len(values),"account":2*(len(highs)+len(lows)),
              "buy_signal":len(highs),"sell_signal":len(lows),"rejected_buy":len(eligible)}
    assert all(trial["counts"].get(k,0)==v for k,v in expected.items())
    observed=trial["rejects"]
    assert [x["time"] for x in observed]==[first+n*STEP for n in eligible]
    assert [D(str(x["last"])) for x in observed]==[values[n] for n in eligible]
    assert all(x["quote_order_qty"]==1 for x in observed)
    lo,hi=D(tape["low"]),D(tape["high"])
    assert lo<=min(values)<=max(values)<=hi
    assert hi/lo==D(tape["max_notional_bound"])<minimum
    assert len(values)*STEP==last-first
    return {"balance":cash,**expected,"min_market_notional":str(minimum),
            "rounded_notional_upper_bound":str(hi/lo),"fills":0,"fees":0,
            "terminal_quote":cash,"terminal_base":0,"first_rejection":observed[0] if observed else None,
            "last_rejection":observed[-1] if observed else None}


def main(job_path,receipt_path,previous_path,worker_path,cap_path,out):
    job_data=job_path.read_bytes()
    job=json.loads(gzip.decompress(job_data))
    worker_data=worker_path.read_bytes()
    receipt_data=receipt_path.read_bytes()
    receipt=json.loads(receipt_data)
    old_reports=json.loads(previous_path.read_bytes())
    assert sha(job_data)==receipt["job_sha256"] and sha(worker_data)==receipt["worker_sha256"]
    assert sha(job["code"].encode())==receipt["source_sha256"]==EXPECTED_HASH
    assert job["args"]=={"PERIOD":60,"LENGTH":1440}
    filt,alt=job["filter_receipts"]
    assert filt["filter"]==alt["filter"]
    diagnostics=[]
    results=[]
    link=("https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/"
          "%E8%BF%BD%E6%B6%A8%E6%9D%80%E8%B7%8C.md")
    for item in job["scopes"]:
        coin=item["coin"]
        date=item["begin_ist"]
        minimum=D(filt["filter"][coin+"USDT"]["min_notional"])
        assert minimum==5
        twins=[x for x in receipt["trials"] if (x["coin"],x["begin_ist"])==(coin,date)]
        assert tuple(x["balance"] for x in twins)==(10_000,100_000)
        first,last=item["begin_ms"],item["end_ms"]
        runs=[verify(item,x,minimum,first,last) for x in twins]
        old=next(x for x in old_reports["order_evidence"] if (x["id"],x["coin"],x["start"])==(5510,coin,date))
        assert old["receipt"]["account"]["Balance"]==10000 and old["receipt"]["account"]["Stocks"]==0
        assert not old["receipt"]["orders"] and not old["receipt"]["resting"]
        assert old["reconciliation"]=={"cash_error":0.0,"asset_error":0.0}
        assert runs[1]["buy_signal"]==runs[1]["rejected_buy"]>0
        diagnostics.append({"symbol":coin+"USDT","from_ist":date,"to_ist":item["end_ist"],"trials":runs,
                            "source_intervals":item["source_intervals"],"previous_cash_reconciliation":old["reconciliation"]})
        results.append(dict(
            id=5510,group="FMZ Native · Binance Spot",name="Buying strength and selling weakness",
            source=link,market=coin+"USDT spot",period=date+" to "+item["end_ist"]+" UTC+05:30",
            interval="1m poll · 1440-tick history",exit="No executable spot buys at source size",
            currency="USDT",quote_currency="USDT",starting_equity=100000,
            trades=0,unsettled=0,gross_wins=0,fee_wins=0,net_wins=0,
            gross=0,after_fees=0,net=0,fees=0,execution=0,funding=0,
            gross_dd=0,fee_dd=0,net_dd=0,gross_dd_pct=0,fee_dd_pct=0,net_dd_pct=0))
    assert len(diagnostics)==len(results)==4
    total=sum(x["trials"][1]["rejected_buy"] for x in diagnostics)
    assert total==653
    report={
        "coverage":[[5510,"Tested · authored ticker breakout on four Binance spot scopes",
          "The pinned Python source with public 60-second/1440-sample defaults completed four BTC/ETH windows. At 100,000 USDT each source buy branch was exercised. All 653 one-USDT market sizes failed the 5-USDT minimum. Independent signals and previous 10,000-USDT cash controls reconcile. Zero fills, fees and drawdown."]],
        "results":results,"diagnostics":diagnostics,"win_rate":None,
        "source":{"publisher":"https://www.fmz.com/strategy/96634","archive_url":link,
                  "archive_sha256":job["archive_sha256"],"source_sha256":EXPECTED_HASH,
                  "parameters":job["args"],"parameter_origin":job["parameter_origin"]},
        "data":{"order_filter_receipts":job["filter_receipts"],"historical_binance_zips":job["market"],
                "primary_notional":"The spot market buy specifies exactly 1 USDT. The public filter applies a 5-USDT minimum to market orders on both pairs. Even an alternate quantity conversion and valuation across the proven observed price envelope cannot reach the minimum."},
        "proof_hashes":{"job":sha(job_data),"isolated_receipt":sha(receipt_data),
                        "worker":sha(worker_data),"staging":sha(cap_path.read_bytes()),
                        "previous_report":sha(previous_path.read_bytes())},
        "assumptions":"The source supplied no venue/date/wallet configuration. The study chooses Binance spot and repeats the prior September/October 2026 windows with 10,000 and 100,000 USDT starting cash, flat inventories and no borrowing. The 100,000-USDT variant supplies all result rows. The current official market-size filter is used as the disclosed replay model. Each ticker value comes from the close of the immediately preceding complete checksum-matched minute, observed strictly before the poll. The lowercase true host alias maps to Python True. The unchanged source sends no sell from zero inventory. Fee differences have no effect because there is no accepted order or execution.",
        "references":[
            "https://www.fmz.com/strategy/96634",
            "https://www.fmz.com/syntax-guide/fun/trade/exchange.buy",
            "https://developers.binance.com/en/docs/products/spot/filters",
            "https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/trade",
            "https://www.binance.com/en/support/announcement/detail/c4706c73b805423a8d36be948e297603"
        ],
    }
    with out.open("x",encoding="utf-8",newline="\n") as writer:writer.write(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print("Four market/date scopes; enriched rejected buys",total,"flat fee ledger independent verification complete")


if __name__=="__main__":
    a=argparse.ArgumentParser(description=__doc__)
    for name in ("job","receipt","previous","worker","capture","output"):a.add_argument(name,type=Path)
    p=a.parse_args()
    main(p.job,p.receipt,p.previous,p.worker,p.capture,p.output)
