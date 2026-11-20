"""Verify market-side, dynamic bet and fee invariants for #595 source scopes."""

import argparse
import csv
import io
import gzip
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone
from zipfile import ZipFile


D=Decimal
PIN="7a7471ae23a3f881ddfa5a23286dd8cdb78409b8301aac7c960957f19b0fe7ba"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def independent(scope,minimum):
    orders=[]
    losing=5
    winning=gears=0
    wager=D("0.001")
    ratio=D(str(scope["proof"]["max_price_ratio"]))
    for i,(sec,local,ex,bar,o,c) in enumerate(scope["samples"]):
        assert sec==scope["start"]+i and local<=sec*1_000_000
        assert ex//60_000_000*60==bar<=sec
        if c>o:
            if losing:
                losing=gears=0
            if wager*ratio>=minimum:
                return orders,sec,"eligible or unverified buy"
            orders.append((sec,"buy",wager))
            winning+=1
            if winning==10:
                winning=gears=0
        elif c<o:
            if winning:gears=0
            if losing==4:
                return orders,sec,"source returned"
            wager*=D("1.5") if gears==0 else D("1.1")
            orders.append((sec,"sell",wager))
            losing+=1
            gears+=1
    return orders,scope["end"],"fixed market boundary"


def official_crosscheck(market, market_dir):
    coin,day=market["coin"],market["day"]
    file=market_dir/f"klines-spot-{coin}USDT-1m-{day}.zip"
    if not file.exists():
        file=market_dir/f"klines-spot-{coin}USDT-1m-{day[:7]}.zip"
    raw=file.read_bytes()
    prior=json.loads((market_dir/"manifest.json").read_bytes())[file.name]
    assert sha(raw)==prior["sha256_or_error"]
    bins={}
    begin,ending=market["start"]-60,market["end"]
    with ZipFile(io.BytesIO(raw)) as archive:
        [name]=archive.namelist()
        with archive.open(name) as fp:
            for row in csv.reader(io.TextIOWrapper(fp,encoding="ascii")):
                t=int(row[0])//1_000_000
                if begin<=t<ending:
                    assert len(row[0])==16 and int(row[6])==int(row[0])+59_999_999
                    bins[t]=tuple(map(D,row[1:5]))
    assert sorted(bins)==list(range(begin,ending,60))
    for sec,seen,ex,bar,o,c in market["samples"]:
        op,hi,lo,close=bins[bar]
        assert ex<=seen<=sec*1_000_000
        assert D(str(o))==op and lo<=D(str(c))<=hi
    return {"source_zip":prior,"bars":len(bins),"matched_active_opens":len(market["samples"]),
            "closes_inside_official_bounds":len(market["samples"])}


def main(job_path,receipt_path,worker_path,stage_path,out):
    job_raw=job_path.read_bytes()
    job=json.loads(gzip.decompress(job_raw))
    receipt_raw=receipt_path.read_bytes()
    receipt=json.loads(receipt_raw)
    assert sha(job_raw)==receipt["job_sha256"]
    assert sha(worker_path.read_bytes())==receipt["worker_sha256"]
    assert sha(job["source"].encode())==receipt["source_sha256"]==PIN
    filt,alt=job["filters"]
    assert filt["filter"]==alt["filter"]
    results=[]; proofs=[]
    url="https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/MartinGale-Strategy1.md"
    for market,trial in zip(job["scopes"],receipt["scopes"],strict=True):
        coin,day=market["coin"],market["day"]
        assert (trial["coin"],trial["day"])==(coin,day)
        crosscheck=official_crosscheck(market,job_path.resolve().parents[1]/"nonpine"/"binance")
        min_notional=D(filt["filter"][coin+"USDT"]["min_notional"])
        assert min_notional==5
        candidates,stops,why=independent(market,min_notional)
        if why=="eligible or unverified buy":
            assert trial["reason"]=="incomplete" and trial["last_second"]==stops
            proofs.append({"coin":coin,"day":day,"classification":"Incomplete eligible intent",
                           "captures":market["proof"],"official_crosscheck":crosscheck,"scope_end":stops,"reason":trial["issue"],
                           "ineligible_performance":True})
            continue
        assert trial["last_second"]==stops and trial["reason"]==why
        assert trial["start_cash"]==trial["cash"]==1_000_000
        assert trial["fills"]==trial["fees"]==trial["stock"]==0
        assert len(candidates)==len(trial["intents"])
        for expected,actual in zip(candidates,trial["intents"],strict=True):
            sec,side,wager=expected
            assert (sec,side)==(actual["second"],actual["side"])
            assert abs(D(str(actual["quantity"]))-wager)<=D("0.000000000001")
            if side=="buy":
                assert abs(D(str(actual["valued_notional_bound"]))-wager*D(str(market["proof"]["max_price_ratio"])))<D("0.000000000001")
                assert D(str(actual["valued_notional_bound"]))<min_notional
            else:
                assert actual["condition"]=="Zero base inventory, sale rejected"
        ticks=stops-market["start"]
        assert trial["record_reads"]==ticks+(why=="source returned")
        assert trial["account_reads"]==ticks
        signs=Counter(t[1] for t in candidates)
        assert signs["buy"] and signs["sell"]
        proofs.append({"coin":coin,"day":day,"classification":"Completed",
                       "captures":market["proof"],"official_crosscheck":crosscheck,"scope_end":stops,"reason":why,
                       "account_checks":ticks,"actions":dict(signs),"biggest_buy_budget":str(max(x[2] for x in candidates if x[1]=="buy")),
                       "ending_cash_USDT":trial["cash"],"ending_base":trial["stock"],"fees_USDT":trial["fees"]})
        cutoff=datetime.fromtimestamp(stops,timezone.utc).strftime("%H:%M:%S")
        results.append(dict(
            id=595,name="MartinGale-Strategy1",group="FMZ Native · Binance Spot",
            source=url,market=coin+"USDT spot",period=day+" 02:00:00–"+cutoff+" UTC",
            interval="1m active bar · 1s polling",exit="Source loss counter or fixed hour boundary",
            currency="USDT",quote_currency="USDT",starting_equity=1_000_000,
            trades=0,unsettled=0,gross_wins=0,fee_wins=0,net_wins=0,
            gross=0,after_fees=0,net=0,fees=0,execution=0,funding=0,
            gross_dd=0,fee_dd=0,net_dd=0,gross_dd_pct=0,fee_dd_pct=0,net_dd_pct=0))
    assert results
    report={
        "coverage":[[595,"Tested · authored Martingale spot size and inventory gates",
          f"{len(results)} preselected historical Binance BTC/ETH scopes completed with the archived variable-size source. Every observed buy remained below the captured size minimum and every sell lacked inventory. The exact signal/count recurrence and flat cash reconciled. Any scope reaching an execution-eligible buy is listed separately without performance."]],
        "results":results,"diagnostics":proofs,"win_rate":None,
        "source":{"archive":url,"archive_sha256":job["archive_sha256"],"source_code_sha256":PIN,
                  "publisher":"https://www.fmz.com/strategy/416875"},
        "filter_receipts":job["filters"],
        "proof_hashes":{"job":sha(job_raw),"native_receipt":sha(receipt_raw),
                        "worker":sha(worker_path.read_bytes()),"stage":sha(stage_path.read_bytes())},
        "scope":"The source supplies no exact saved venue/date/timeframe. This study applies its original one-million cash anchor and dynamic decisions to benign Binance spot history. Four first-of-month BTC/ETH windows were fixed before outcome inspection. One-second polls use the captured current one-minute open and latest observed close. Start flat in base inventory, with no borrowing or order resizing. Program-driven termination by its unchanged counter remains a complete scope.",
        "fee_evidence":"The current public Binance exchange filter is used as the scoped model. A one-second price path can change the proposed size above its initial value, so the study independently checks every attempted buy. Market buys use quote currency. Sources with no accepted orders incur no cost, regardless of fee tier. No market-filling path was inferred.",
        "references":["https://www.fmz.com/syntax-guide/fun/trade/exchange.buy",
                      "https://developers.binance.com/en/docs/products/spot/filters",
                      "https://docs.tardis.dev/historical-data-details/binance"],
    }
    with out.open("x",encoding="utf-8",newline="\n") as file:file.write(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print([(p["coin"],p["day"],p["classification"],p.get("actions"),p.get("biggest_buy_budget")) for p in proofs])


if __name__=="__main__":
    helper=argparse.ArgumentParser(description=__doc__)
    for name in ("job","receipt","worker","stage","output"):helper.add_argument(name,type=Path)
    p=helper.parse_args()
    main(p.job,p.receipt,p.worker,p.stage,p.output)
