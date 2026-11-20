"""Verify #2401 signal timing, marketable fills and BTC inverse accounting."""

import argparse
from collections import defaultdict
from decimal import Decimal, localcontext
from hashlib import sha256
from math import isclose, log
from pathlib import Path
import gzip
import json

D = Decimal
ONE = D(1)
ZERO = D(0)
N = 90
SIZE = 100
STEP = 900
US = 1_000_000
TAKER = D("0.00075")
EPS = D("0.00000000000001")
TINY = float.fromhex("0x0.0000000000001p-1022")
ARCHIVE_URL = ("https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/"
               "%E5%90%95%E7%A5%9E-%E7%AE%80%E6%98%93%E6%B3%A2%E5%8A%A8%E7%8E%87%E7%AD%96%E7%95%A5.md")


def d(x):
    return D(str(x))


def near(actual, expected):
    assert abs(d(actual)-expected)<=EPS, (actual,expected)


def sha(raw):
    return sha256(raw).hexdigest()


def max_drawdown(balance, changes):
    peak=balance
    worst=fraction=ZERO
    for delta in changes:
        value=balance+delta
        peak=max(peak,value)
        worst=max(worst,peak-value)
        fraction=max(fraction,(peak-value)/peak)
    return worst,fraction


def verify_candles(spec):
    captured={r[0]:r[4] for r in spec["intra_trade_candle_ohlc"]}
    assert len(captured)==96
    assert len(spec["history"])==200 and all(r[4]>0 for r in spec["history"])
    assert [r[0] for r in spec["history"]]==list(range(spec["begin"]-200*STEP,spec["begin"],STEP))
    assert sum(r[0] in captured for r in spec["history"])==8
    assert all(r[4]==captured[r[0]] for r in spec["history"] if r[0] in captured)
    assert all(p["mirrors_close_equal"]==96 for p in spec["mirror_references"])
    samples=spec["data"]
    assert [r[0] for r in samples]==list(range(spec["begin"],spec["end"]+1,5))
    assert all(t*US>=trade[0]>=trade[1] and t*US>=quote[0]>=quote[1] and t*US>=mark[0]>=mark[1]
               for t,trade,quote,mark in samples)


def verify_signals(spec, replay):
    bars=[(r[0],r[4]) for r in spec["history"]]
    vol=[]
    band=[]
    means=[]
    seen=0
    expected_orders=[]
    indicator_trace=iter(replay["indicators"])
    position=0

    def accumulate(current, lag):
        nonlocal seen
        if current[0]==seen:
            return
        seen=current[0]
        vol.append(log(current[1])/log(lag[1])-1)
        if len(vol)>N:
            prior=vol[-N-1:-1]
            band.append((max(TINY,*prior),min(prior)))
            means.append(sum(vol[-N:])/N)

    def set_active(trade):
        current=(trade[2],trade[6])
        if current[0]>bars[-1][0]:
            assert current[0]==bars[-1][0]+STEP
            bars.append(current)
        else:
            assert current[0]==bars[-1][0]
            bars[-1]=current

    set_active(spec["data"][0][1])
    for i in range(-2,N-1):
        accumulate(bars[len(bars)-N+i],bars[len(bars)-2*N+i])
    assert len(vol)==91 and len(band)==1
    for t,trade,quote,mark in spec["data"][:-1]:
        set_active(trade)
        current=bars[-1]
        lag=bars[len(bars)-N]
        first_seen=current[0]!=seen
        accumulate(current,lag)
        current_vol,prior_vol=vol[-1],vol[-2]
        high,low=band[-1]
        previous_high,previous_low=band[-2]
        if first_seen:
            checked=next(indicator_trace)
            assert checked[:2]==[t,current[0]*1000] and checked[-2:]==[current[1],lag[1]]
            actual=[current_vol,high,low,means[-1]]
            assert all(isclose(a,b,rel_tol=0,abs_tol=2e-15) for a,b in zip(checked[2:6],actual,strict=True)), (t,actual,checked)
        previous=position
        if previous==0 and current_vol>high and prior_vol<=previous_high:
            expected_orders.append((t,"buy",quote[3]))
            position=SIZE
        if previous==0 and current_vol<low and prior_vol>=previous_low:
            expected_orders.append((t,"sell",quote[2]))
            position=-SIZE
        if previous>0 and current_vol<means[-1] and prior_vol>=means[-2]:
            expected_orders.append((t,"closebuy",quote[2]))
            position=0
        if previous<0 and current_vol>means[-1] and prior_vol<=means[-2]:
            expected_orders.append((t,"closesell",quote[3]))
            position=0
    assert next(indicator_trace,None) is None
    native=[(x["at"],x["direction"],x["price"]) for x in replay["orders"]]
    assert native==expected_orders
    return expected_orders


def verify_financial(spec, replay):
    assert len(replay["points"])==len(spec["data"])==14_401
    assert replay["counts"]["ticker"]==replay["counts"]["sleep"]==14_400
    assert replay["counts"]["records"]==14_401
    balance=cash=d(spec["wallet_xbt"])
    qty=0
    entry=entry_last=fee_open=carry_open=ZERO
    fees_total=funding_total=exec_total=ZERO
    rounding=ZERO
    open_capital=None
    trades=[]
    curves=defaultdict(list)
    orders={r["at"]:r for r in replay["orders"]}
    carries={f["at"]:f for f in replay["funding"]}
    assert len(orders)==len(replay["orders"]) and len(carries)==3
    assert orders.keys().isdisjoint(carries)
    for row, native in zip(spec["data"],replay["points"],strict=True):
        t,trade,quote,mark=row
        if t in carries:
            f=carries[t]
            around=spec["funding_near"][str(t)]
            prior=[r for r in around if r[4]==t*US and r[0]<=t*US][-1]
            rolled=next(r for r in around if r[4]>t*US)
            assert f["prior"]==prior and f["later"]==rolled
            assert f["qty"]==qty and f["rate"]==float(prior[5])
            v=-d(qty)/d(prior[2])*d(prior[5]); alt=-d(qty)/d(rolled[2])*d(prior[5])
            near(f["amount"],v)
            cash+=v
            carry_open+=v
            funding_total+=v
            rounding+=abs(v-alt)
            near(f["cash"],cash)
        if t in orders:
            o=orders[t]
            assert o["quote"]==quote and o["amount"]==SIZE
            side=o["side"]
            assert side in (1,-1)
            assert 0<=t*US-quote[0]<=5*US and quote[9 if side==1 else 8]
            assert quote[7 if side==1 else 6]>=SIZE
            px,last=d(o["price"]),d(trade[6]); signed=d(side*SIZE)
            assert px==d(quote[3 if side==1 else 2])
            f=d(SIZE)/px*TAKER
            e=signed*(ONE/last-ONE/px)
            fees_total+=f
            exec_total+=e
            near(o["fee"],f); near(o["slip"],e)
            cash-=f
            if o["open"]:
                assert qty==0 and carry_open==0
                qty=side*SIZE
                open_capital=[o["id"],e]
                entry,entry_last,fee_open=px,last,f
                near(o["gross"],ZERO)
            else:
                assert qty==-side*SIZE and open_capital
                proof=qty*(ONE/entry_last-ONE/last)
                actual=qty*(ONE/entry-ONE/px)
                execution=open_capital[1]+e
                near(o["gross"],actual)
                assert abs(proof-execution-actual)<D("1e-36")
                cash+=actual
                fee=fee_open+f
                trades.append({"entry_order":open_capital[0],"exit_order":o["id"],
                    "gross":proof,"gross_at_fills":actual,"fees":fee,"execution":execution,
                    "after_fees":proof-fee,"after_fees_at_fills":actual-fee,
                    "funding":carry_open,"net":actual-fee+carry_open})
                qty=0
                entry=entry_last=fee_open=carry_open=ZERO
                open_capital=None
            near(o["cash"],cash)
        new_mark=d(mark[2])
        unrealized=qty*(ONE/entry-ONE/new_mark) if qty else ZERO
        maintenance=abs(d(qty))/new_mark*(D("0.005")+TAKER)
        assert cash+unrealized-maintenance>D("1.98")
        assert native[0]==t and native[2]==qty and native[3]==float(entry) and native[5]==float(new_mark)
        near(native[1],cash); near(native[4],unrealized); near(native[6],exec_total)
        curves["net"].append(cash-balance+unrealized)
        curves["after_fees"].append(curves["net"][-1]-funding_total)
        curves["gross"].append(curves["after_fees"][-1]+fees_total)
    assert len(trades)==1 and qty==-SIZE and open_capital is not None
    near(replay["ending"]["cash"],cash)
    near(replay["ending"]["unrealized"],unrealized)
    assert abs(curves["net"][-1]-trades[0]["net"]-unrealized+fee_open-carry_open)<D("1e-36")
    results=trades[0]
    outcome={key:float(results[key]) for key in ("gross","fees","execution","after_fees","funding","net")}
    for a,b in (("gross","gross"),("fee","after_fees"),("net","net")):
        abs_dd,pct_dd=max_drawdown(balance,[results[b]])
        outcome[a+"_dd"]=float(abs_dd)
        outcome[a+"_dd_pct"]=float(pct_dd)
    outcome["gross_wins"]=int(results["gross"]>0)
    outcome["fee_wins"]=int(results["after_fees"]>0)
    outcome["net_wins"]=int(results["net"]>0)
    assert abs(d(outcome["after_fees"])-d(outcome["execution"])+d(outcome["funding"])-d(outcome["net"]))<EPS
    outcome.update(id=2401,market="BitMEX XBTUSD perpetual [BTC settlement]",period=replay["day"]+" 02:00–22:00 UTC",
        group="FMZ Native · BitMEX inverse volatility breakout",name="吕神-简易波动率策略",source=ARCHIVE_URL,
        interval="15m chart · 5s poll",exit="Archived midline crossing · open short carried at cutoff",
        currency="BTC",quote_currency="BTC",currency_decimal_places=12,trades=1,unsettled=1,
        starting_equity=float(balance),mark_to_market_net=float(curves["net"][-1]),remaining_unrealized=float(unrealized))
    details={"day":replay["day"],"order_events":replay["orders"],"funding_events":replay["funding"],
        "closed_trade_BTC":{k:str(v) if isinstance(v,D) else v for k,v in results.items()},
        "ending_open_BTC":{"position_contracts":qty,"entry_USD":str(entry),"entry_fee":str(fee_open),
                           "funding":str(carry_open),"unrealized":str(unrealized)},
        "ending_wallet_BTC":str(cash),"maximum_adjacent_funding_mark_sensitivity_BTC":str(rounding),
        "fractional_satoshi_fee_funding_bound_BTC":str(d(len(orders)+len(carries))/D("100000000")),
        "drawdown_on_five_second_marked_equity":{k:{"BTC":str(v[0]),"fraction":str(v[1])}
                   for k,c in curves.items() if (v:=max_drawdown(balance,c))},
        "market_capture":spec["captures"],"warmup_references":spec["mirror_references"],
        "same_day_receipt_crosschecks":spec["market_crosscheck"],"indicator_events":len(replay["indicators"]),
        "ta_highest_nonpositive_windows":replay["negative_band_windows"],
        "no_order_stale_quote_observations":replay["stale_quotes_with_no_orders"]}
    return outcome,details


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job",type=Path,required=True)
    ap.add_argument("--receipt",type=Path,required=True)
    ap.add_argument("--worker",type=Path,required=True)
    ap.add_argument("--stage",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    staged=args.job.read_bytes()
    receipt=args.receipt.read_bytes()
    job=json.loads(gzip.decompress(staged))
    replay=json.loads(receipt)
    assert sha(staged)==replay["job_sha256"] and sha(job["source"].encode())==replay["source_sha256"]==job["source_sha256"]
    assert replay["network_requests"]==0
    assert [s["day"] for s in replay["scopes"]]==list(job["scenarios"])
    records=[]
    diagnostics=[]
    with localcontext() as precision:
        precision.prec=44
        for s in replay["scopes"]:
            bound=job["scenarios"][s["day"]]
            verify_candles(bound)
            six=verify_signals(bound,s)
            assert len(six)==3
            row,data=verify_financial(bound,s)
            records.append(row)
            diagnostics.append(data)
    report={"coverage":[[2401,"Tested · archived BitMEX volatility breakout in two causal BTC scopes",
        "Replayed the exact archived N=90 and 100-contract BitMEX XBTUSD strategy on two 20-hour slices within its published dates. Independent checks matched all decisions and BTC accounting. Each slice closed one long and carried one open short. Net win rate 0/2. Full original year and ETH are outside this evidence."]],
        "results":records,"diagnostics":diagnostics,
        "source":{"id":2401,"publisher":"https://www.fmz.com/strategy/200131","archive_url":ARCHIVE_URL,
                "archive_path":job["archive_path"],"archive_document_sha256":job["archive_sha256"],
                "archived_source_sha256":job["source_sha256"],"settings":job["settings"]},
        "inputs":{"staged_sha256":sha(staged),"receipt_sha256":sha(receipt),"native_engine_sha256":replay["native_engine_sha256"],
                  "worker_sha256":sha(args.worker.read_bytes()),"stage_sha256":sha(args.stage.read_bytes()),
                  "verifier_sha256":sha(Path(__file__).read_bytes())},
        "method":{"market":"Exactly the authored XBTUSD venue/product. Free first-of-month UTC windows within the source period, flat with 2 virtual BTC collateral. No original wallet size published. The dates and 20-hour scopes were set before replay. One unresolved position at cutoff is marked separately in each window without forced liquidation.",
          "signals":"Run the archived JavaScript in a network-denied worker using FMZ's native WASM TA.MA/Highest/Lowest. The source computes volatility once on the first available 5-second poll per new 15-minute bar, using the price then available. During initialization the archived lookback index differs by one from the live loop. Native Highest/Lowest exclude the current array element. Highest uses Number.MIN_VALUE for all-nonpositive pre-windows, which did not affect either measured scope. The Decimal ledger verifier independently replays the signals with a Python math calculation.",
          "warmup":"200 causal XBTUSD closes seeded from a pinned exchange-API mirror. Its own 1m and 5m daily archives produce the same 96 closes for all six dates, and all sixteen overlapping seed closes match independent normalized raw trades. Across the two full replay dates, 191/192 complete-bar closes and 130/192 entire OHLC vectors match; API open conventions and boundary publication differ. Indicator entries after startup use the causal raw trade path. The FMZ Q 15m archive was independently rejected as not exact, and is unused.",
          "fills":"Every programmed limit crosses the observed best bid or ask. Full 100-contract size is verified at that price for the ensuing 100ms of market quotes. Source identical executable logic uses neutral plotting output sinks. Delays beyond 100ms and counterfactual market impact are not estimated. Position equity exceeds 1.98 BTC above the maintenance and exit reserve throughout.",
          "accounting":"Inverse USD-face contracts with native BTC settlement. Compare against entry and exit last-trade references to attribute pure execution cost separately. Gross is pre-fee reference P&L. Fee and funding models are separately pinned; venue 0.075% taker and the capture's scheduled funding rate and last pre-roll mark. Closed-trade P&L includes only fees and funding attributable to closed positions. Separate diagnostics give actual fill-price gross/after-fee P&L and realized-plus-open marked drawdown. No ETH history substitution or scaling.",
          "precision":"Simulated amounts use continuous inverse contract math and fractional-satoshi precision. Decimal reconciliation independently matches every native cash/position/mark and source decision. Funding sensitivity uses the first observed rolled mark, and the separate rounding envelope allows up to one satoshi per debit/credit event."},
        "reproduction":"Run the stage with --archive and --output, using the published R20 BitMEX capture helper beside it. Run the worker in the existing offline AppContainer with the staged job named round26-2401-xbtusd-tape.json.gz. Verify the resulting receipt with --job --receipt --worker --stage --output.",
        "reference_urls":["https://www.fmz.com/strategy/200131","https://www.fmz.com/syntax-guide/fun/ta/ta.highest",
            "https://www.fmz.com/syntax-guide/fun/ta/ta.lowest","https://docs.tardis.dev/historical-data-details/bitmex",
            "https://github.com/Celeborn2BeAlive/bitmex-xbtusd-history/tree/8e3e1a5eaeaf1af4de4fd77dbecca5deb644c5b9",
            "https://docs.bitmex.com/api-explorer/get-trade-bucketed","https://www.bitmex.com/blog/why-we-revamped-our-fee-structure"]}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    print("verified",len(records),"scopes",sum(r["trades"] for r in records),"closed trades",sha(args.output.read_bytes()))
    print([(r["period"],r["gross"],r["after_fees"],r["net"],r["net_dd"],r["mark_to_market_net"]) for r in records])


if __name__=="__main__":
    main()
