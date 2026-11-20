"""Independent least-squares derivative and EMA state for the saved Delta RSI."""
import math
import sys
from pathlib import Path
from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round40_4307 import recurrence

def solve(matrix, target):
    basis=[list(row)+[b] for row,b in zip(matrix,target,strict=True)]
    for col in range(len(basis)):
        pick=max(range(col,len(basis)),key=lambda k:abs(basis[k][col]))
        basis[col],basis[pick]=basis[pick],basis[col]
        value=basis[col][col]
        assert abs(value)>1e-9
        basis[col]=[n/value for n in basis[col]]
        for j,row in enumerate(basis):
            if j!=col:
                scale=row[col]
                basis[j]=[a-scale*b for a,b in zip(row,basis[col],strict=True)]
    return [item[-1] for item in basis]

def fit(ref, window=50):
    x=[2*p/(window-1)-1 for p in range(window)]
    gram=[[math.fsum(p**(a+b) for p in x) for a in range(4)] for b in range(4)]
    diff, nrmse = [], []
    for i in range(len(ref)):
        period=ref[max(0,i-window+1):i+1]
        a=b=None
        if len(period)==window and None not in period:
            moment=[math.fsum(y*p**k for y,p in zip(period,x,strict=True)) for k in range(4)]
            coef=solve(gram,moment)
            a=(coef[1]+2*coef[2]+3*coef[3])*2/(window-1)
            estimate=[math.fsum(c*p**k for k,c in enumerate(coef)) for p in x]
            b=math.sqrt(math.fsum((y-z)**2 for y,z in zip(period,estimate,strict=True))/window)/(math.fsum(period)/window)
        diff.append(a)
        nrmse.append(b)
    return diff,nrmse

def outputs(candles, ema_seed):
    close=[r[4] for r in candles]
    changes=[b-a for a,b in zip(close,close[1:])]
    up=recurrence([max(v,0) for v in changes],21,1/21)
    down=recurrence([max(-v,0) for v in changes],21,1/21)
    rsi=[None,*[None if a is None else 100 if b==0 else 100-100/(1+a/b) for a,b in zip(up,down,strict=True)]]
    d,rm=fit(rsi)
    ema=recurrence(d,ema_seed,.2)
    buy,sell=[],[]
    for i in range(1,len(d)):
        prev,cur,pref,sig=d[i-1],d[i],ema[i-1],ema[i]
        if None not in (prev,cur,pref,sig):
            if cur>sig and prev<=pref:
                buy.append(i)
            if cur<sig and prev>=pref:
                sell.append(i)
    return {"RSI":rsi,"DRSI":d,"NRMSE":rm,"signal":ema,"buy":buy,"sell":sell}


SOURCE = "69e8340f3130ee9e6563864f2a4f800e2ce8dc99fb1bc0177d23b2d3f72f1824"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000
FEE = .00075


def path(candles, base, broker, buys, sells):
    known,closed=[],[]
    state=0
    opened=None
    cash=float(CAPITAL)
    for i,(bar,mark) in enumerate(zip(candles,broker["equity"],strict=True)):
        stamp,op,_,_,close,_=bar
        assert bar[:2]==base[4*i][:2]
        up=i-1 in buys
        down=i-1 in sells
        assert not (up and down)
        prior=state
        desired=1 if up else -1 if down and prior!=-1 else 0 if down else prior
        if state != desired:
            if state:
                e_idx,e_ts,e_price=opened
                gross=(op-e_price)*state
                commission=(op+e_price)*FEE
                closed.append({"dir":state,"qty":1,"entryPrice":e_price,"entryTime":e_ts,"entryBar":e_idx,
                               "exitPrice":op,"exitTime":stamp,"exitBar":i,"commission":commission,
                               "gross":gross,"profit":gross-commission})
                cash+=op*state
                if down:
                    known.append(("strategy.close",i,stamp,1,op))
            if desired:
                size=2 if up and prior==-1 else 1
                known.append(("strategy.long" if desired>0 else "strategy.short",i,stamp,size,op))
                cash-=op*desired
                opened=i,stamp,op
            else:
                opened=None
            state=desired
        value=state*close
        for name,expected in (("cash",cash),("marketValue",value),
                              ("equity",cash+value),("netProfit",cash+value-CAPITAL)):
            assert math.isclose(mark[name],expected,rel_tol=0,abs_tol=1e-8),(i,name,mark,expected)
    assert known==[(o["direction"],o["barIndex"],o["time"],o["qty"],o["price"]) for o in broker["orders"]]
    for got,want in zip(broker["trades"],closed,strict=True):
        assert (got["entryBarIndex"],got["exitBarIndex"],got["entryPrice"],got["exitPrice"],got["qty"])==(
            want["entryBar"],want["exitBar"],want["entryPrice"],want["exitPrice"],want["dir"])
        assert math.isclose(got["profit"],want["gross"],rel_tol=0,abs_tol=1e-8)
    assert opened and state in (-1,1)
    _, time, entry=opened
    mark=candles[-1][4]
    return {"orders":known,"trades":closed,"terminal":{"direction":state,"entry":entry,"entry_time":time,
            "mark":mark,"gross_unrealized":(mark-entry)*state,
            "net_unrealized_if_closed_at_last_mark":(mark-entry)*state-(mark+entry)*FEE}}


def audit(market,feed,rows):
    assert [len(feed[k]) for k in ("chart","base")]==[168,672]
    assert rows["literal"]["errors"][0].startswith("E_ASSIGN_TYPE")
    assert rows["typed_init"]==rows["typed_fallback"]
    assert rows["documented_first_ema"]==rows["documented_ema_no_brackets"]
    choices={}
    for seed,key,label in ((1,"documented_first_ema","fmz_documented_seed"),(9,"typed_fallback","native_sma_seed")):
        good=rows[key]
        assert not good["diagnostics"] and not good["broker"]["diagnostics"]
        expected=outputs(feed["chart"],seed)
        for p in ("RSI","DRSI","NRMSE","signal"):
            values=good["plots"]["scope "+p]
            assert all(a==b or (None not in (a,b) and math.isclose(a,b,abs_tol=1e-8))
                       for a,b in zip(values,expected[p],strict=True)),(market,seed,p)
        for p in ("buy","sell","end long","end short"):
            signals=[i for i,v in enumerate(good["plots"]["scope "+p]) if v]
            assert signals==expected["buy" if p=="buy" else "sell"]
        model=path(feed["chart"],feed["base"],good["broker"],expected["buy"],expected["sell"])
        choices[label]={**model,"buy_signal_bars":expected["buy"],"sell_signal_bars":expected["sell"]}
    assert choices["fmz_documented_seed"]["orders"]!=choices["native_sma_seed"]["orders"]
    return {"market":market,"literal_compile_error":rows["literal"]["errors"][0],"variants":choices}


def main(work,out):
    assert sha256(work/"source-3309.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    raw,feed=work/"3309-native.json",work/"3309-feed.json"
    data,replay=read(feed),read(raw)
    assert len(data["receipts"])==2
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    cases=[audit(m,f,replay[m]) for m,f in data["markets"].items()]
    attrs={"id":3309,"group":"FMZ Pine v4 · documented first-value EMA",
           "exit":"Authored D-RSI signal crosses and named market closes",
           "period":"Binance USD-M · 2024-01-04 to 2024-01-11 UTC exclusive",
           "interval":"1h","archive_interval":"1h","currency":"USDT"}
    rows=[{**attrs,"market":c["market"],**ledger_metrics(
        c["variants"]["fmz_documented_seed"]["trades"],CAPITAL,1)} for c in cases]
    rows.append({**attrs,"market":"BTCUSDT + ETHUSDT",**ledger_metrics(
        [t for c in cases for t in c["variants"]["fmz_documented_seed"]["trades"]],2*CAPITAL,2)})
    write(out,{"schema":"FMZ #3309 verified QR derivative, documented EMA seed and market ledger",
               "source_url":"https://www.fmz.com/strategy/438479",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"input_sha256":sha256(feed),
               "native_sha256":sha256(raw),"market_receipts":data["receipts"],
               "fee_sensitivity_per_side":FEE,"isolation":isolation,"cases":cases,
               "coverage":[[3309,"Tested · documented EMA seed and verified cubic fit",
                            "A typed local fallback preserves the original QR computation. The FMZ-documented first-value EMA supplies the benchmark, with the distinct native SMA-seed sensitivity disclosed. Both default executions reconcile every trade, mark and 15m next-open price."]],
               "results":rows})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
