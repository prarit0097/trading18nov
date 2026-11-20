"""Independent HA, indicator and order reconciliation for the saved FMZ #2708 window."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read,sha256,write

SOURCE="d7706e4a0a541a448681803705cbc6c10f385ba4f44bdd8c574ccc0f3fef82f3"
ENGINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL=1_000_000
FEE=.00075
HOUR=3600_000


def strict(a,b,d):
    return a is not None and b is not None and (a>b if d>0 else a<b)


def cross(series,other,i,d,shift=0):
    if i<=shift:
        return False
    a,b,p,q=series[i-shift],other[i],series[i-shift-1],other[i-1]
    return strict(a,b,d) and p is not None and q is not None and not strict(p,q,d)


def series_equal(a,b):
    return all((x is None and y is None) or
               (x is not None and y is not None and math.isclose(x,y,abs_tol=1e-7,rel_tol=0))
               for x,y in zip(a,b,strict=True))


def heikin(rows):
    out=[]
    for _,op,high,low,close,_ in rows:
        start=(op+close)/2 if not out else (out[-1][0]+out[-1][3])/2
        last=(op+high+low+close)/4
        out.append((start,max(high,start,last),min(low,start,last),last))
    return list(zip(*out,strict=True))


def finite_window(data,i,n):
    block=data[max(0,i-n+1):i+1]
    return block if len(block)==n and all(v is not None for v in block) else []


def average(data,n,weighted=False):
    out=[]
    for i in range(len(data)):
        tail=finite_window(data,i,n)
        if not tail:
            out.append(None)
        elif weighted:
            out.append(sum(v*(ix+1) for ix,v in enumerate(tail))/(n*(n+1)/2))
        else:
            out.append(sum(tail)/n)
    return out


def rma(data,n):
    out=[]
    for i,x in enumerate(data):
        if x is None:
            out.append(None)
            continue
        prev=out[-1] if out else None
        tail=finite_window(data,i,n)
        out.append(prev+(x-prev)/n if prev is not None else sum(tail)/n if tail else None)
    return out


def ema(data,n):
    out=[]
    for value in data:
        out.append(value if not out else out[-1]+2*(value-out[-1])/(n+1))
    return out


def source_curves(chart):
    _,op,high,low,close,_=zip(*chart,strict=True)
    h_o,h_h,h_l,h_c=heikin(chart)
    tr=[None]+[max(h-l,abs(h-prev),abs(l-prev)) for h,l,prev in zip(high[1:],low[1:],close[:-1],strict=True)]
    atr=rma([high[0]-low[0],*tr[1:]],4)
    atr_mean=average(tr,5)
    band_center=[(h+l)/2 for h,l in zip(high,low,strict=True)]
    upper,lower,trail,trend=[] ,[],[],[]
    for i, (mid,vol) in enumerate(zip(band_center,atr,strict=True)):
        top=mid+2*vol if vol is not None else None
        bottom=mid-2*vol if vol is not None else None
        last_upper,last_lower=(upper[-1],lower[-1]) if i else (None,None)
        previous_close=h_c[i-1] if i else None
        lower.append(max(bottom,last_lower) if bottom is not None and strict(previous_close,last_lower,1) else bottom)
        upper.append(min(top,last_upper) if top is not None and strict(previous_close,last_upper,-1) else top)
        side=1 if strict(h_c[i],last_upper,1) else -1 if strict(h_c[i],last_lower,-1) else trend[-1] if i else 1
        trend.append(side)
        trail.append(lower[-1] if side==1 else upper[-1])
    cci=[]
    for i,x in enumerate(close):
        tail=finite_window(close,i,20)
        mean=sum(tail)/20 if tail else None
        dev=sum(abs(v-mean) for v in tail)/20 if tail else None
        cci.append((x-mean)/(.015*dev) if dev else None)
    ccitrail,up,down=[],[],[]
    for i,a in enumerate(cci):
        p=cci[i-1] if i and cci[i-1] is not None else 0
        bdn=high[i]+atr_mean[i] if atr_mean[i] is not None else None
        bup=low[i]-atr_mean[i] if atr_mean[i] is not None else None
        prev_up=up[-1] if i else None
        prev_dn=down[-1] if i else None
        if a is not None:
            if a>=0 and p<0:
                bup=prev_dn
            if a<=0 and p>0:
                bdn=prev_up
            if a>=0 and strict(bup,prev_up,-1):
                bup=prev_up
            if a<0 and strict(bdn,prev_dn,1):
                bdn=prev_dn
        up.append(bup)
        down.append(bdn)
        ccitrail.append((bup if a>=0 else bdn) if a is not None else ccitrail[-1] if i else None)
    hma=average([2*y-z if z is not None else None
                 for y,z in zip(average(h_c,7,True),average(h_c,15,True),strict=True)],4,True)
    e20=ema(h_c,20)
    diff=[None]+[j-i for i,j in zip(close[:-1],close[1:],strict=True)]
    gains=rma([max(q,0) if q is not None else None for q in diff],14)
    losses=rma([max(-q,0) if q is not None else None for q in diff],14)
    rsi=[(100 if s==0 else 100-100/(1+g/s)) if g is not None and s is not None else None
         for g,s in zip(gains,losses,strict=True)]
    return {"ha_open":h_o,"ha_high":h_h,"ha_low":h_l,"ha_close":h_c,"tsi":trail,
            "trend":trend,"tempx":ccitrail,"htfx":[None]+ccitrail[:-1]}, e20,hma,rsi,close


def source_gates(chart,curves,e20,hma,rsi,close):
    p=curves
    trade_flags=[]
    previous=[0,0]
    for i,row in enumerate(chart):
        cv,op,hi,lo=(p[k][i] for k in ("ha_close","ha_open","ha_high","ha_low"))
        source_close=close[i]
        active=p["htfx"][i]
        stop=p["tsi"][i]
        up=strict(cv,stop,1) or any(cross(p["ha_close"],p["tsi"],i,1,offset) for offset in (0,1,2))
        down=strict(cv,stop,-1) or any(cross(p["ha_close"],p["tsi"],i,-1,offset) for offset in (0,1,2))
        long=op==lo and up and strict(source_close,active,1) and any(
            strict(cv,k,1) and strict(lo,k,-1) for k in (e20[i],hma[i]))
        short=op==hi and down and strict(source_close,active,-1) and strict(rsi[i],55,-1) and any(
            strict(cv,k,-1) and strict(hi,k,1) for k in (e20[i],hma[i]))
        touch=cross(close,p["tempx"],i,1) or cross(close,p["tempx"],i,-1)
        date_close=row[0]//HOUR%24==16
        state=[1 if gate else 2 if touch else previous[t] for t,gate in enumerate((long,short))]
        trade_flags.append((int(state[0]==1 and previous[0]!=1),int(state[1]==1 and previous[1]!=1),
                            int(touch or date_close),int(date_close),*state))
        previous=state
    return trade_flags


def audit_lots(chart,base,flags,actual):
    realized=CAPITAL
    lots=[]
    open_lot=None
    orders=iter(actual["orders"])
    trades=iter(actual["trades"])
    for i in range(1,len(chart)):
        l,s,cl,_,_,_=flags[i-1]
        assert not (l and s)
        time,op=chart[i][:2]
        assert list(base[i*16][:2])==chart[i][:2]
        requested="long" if l else "short" if s else None
        if open_lot and (cl or (requested and requested!=open_lot[0])):
            label, open_i,opened_time,entry=open_lot
            native=next(trades)
            direction=1 if label=="long" else -1
            assert (native["id"],native["entryBarIndex"],native["exitBarIndex"],native["qty"])==(label,open_i,i,direction)
            assert (opened_time,time,entry,op)==tuple(native[k] for k in ("entryTime","exitTime","entryPrice","exitPrice"))
            pnl=direction*(op-entry)
            assert math.isclose(pnl,native["profit"],abs_tol=1e-8)
            realized+=pnl
            if cl:
                report=next(orders)
                assert (report["direction"],report["id"],report["time"],report["price"],report["qty"])==(
                    "strategy.close","Close entry(s) order "+label,time,op,1)
            fee=FEE*(entry+op)
            lots.append({**native,"qty":1,"dir":direction,"profit":pnl-fee,"commission":fee})
            open_lot=None
        if requested and open_lot is None:
            match=next(orders)
            assert (match["id"],match["time"],match["price"])==(requested,time,op)
            assert match["qty"]==1
            open_lot=(requested,i,time,op)
        native_position=actual["equity"][i]
        assert native_position["marketValue"] == (0.0 if open_lot is None else chart[i][4]*(1 if open_lot[0]=="long" else -1))
        floating=0.0 if open_lot is None else (chart[i][4]-open_lot[3])*(1 if open_lot[0]=="long" else -1)
        assert math.isclose(native_position["equity"],realized+floating,abs_tol=1e-7)
    assert next(orders,None) is None and next(trades,None) is None and open_lot is None
    return lots


def main(work,out):
    feeds=work/"2708-inputs.json"
    replay=work/"2708-probe.json"
    assert sha256(work/"source-2708.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(error[0]=="PermissionError" for error in isolation.values())
    data=read(feeds)
    report=read(replay)
    scopes,rows,pooled=[],[],[]
    common={"id":2708,"group":"FMZ Pine v4 · Heikin-Ashi and CCI close",
            "exit":"CCI line crossover, scheduled UTC close, or reversal",
            "period":"Binance USD-M · 2024-01-06 to 2024-02-05 UTC exclusive",
            "interval":"4h","archive_interval":"4h","currency":"USDT"}
    for d,r,count in zip(data["cases"],report,(7,8),strict=True):
        c=d["chart"]
        assert len(c)==180 and d["market"]==r["market"]
        live=r["literal"]
        assert live["broker"]==r["portable"]["broker"] and live["plots"]==r["portable"]["plots"]
        assert [diag["code"] for diag in live["diagnostics"]]==["W_LEGACY_SECURITY_LOOKAHEAD"]*2
        v=live["plots"]
        p,e,h,rs,cl=source_curves(c)
        for k,value in p.items():
            if not series_equal(v[k],value):
                print(d["market"],k,[(i,a,b) for i,(a,b) in enumerate(zip(v[k],value,strict=True))
                                     if not series_equal([a],[b])][:5])
                raise ValueError(k)
        expected=source_gates(c,p,e,h,rs,cl)
        actual=list(zip(*(v[k] for k in ("long","short","close","session_close","longstate","shortstate")),strict=True))
        if actual!=expected:
            print("flags",d["market"],[(i,a,b) for i,(a,b) in enumerate(zip(actual,expected,strict=True)) if a!=b][:7])
            raise ValueError("gates")
        assert sum(r[3] for r in actual)==30
        lots=audit_lots(c,d["base"],expected,live["broker"])
        assert len(lots)==count
        scopes.append({"market":d["market"],"lots":lots,"chart_count":len(c),
                       "confirmed_htf_equal":len(c),"utc_close_flags":30})
        rows.append({**common,"market":d["market"],**ledger_metrics(lots,CAPITAL,0)})
        pooled.extend(lots)
    rows.append({**common,"market":"BTCUSDT + ETHUSDT",**ledger_metrics(pooled,CAPITAL*2,0)})
    write(out,{
        "schema":"FMZ #2708 complete archived Heikin-Ashi and CCI SuperTrend replay",
        "source_url":"https://www.fmz.com/strategy/441178",
        "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256":SOURCE,"engine_sha256":ENGINE,"input_sha256":sha256(feeds),
        "runtime_output_sha256":sha256(replay),"input_archives":data["source_files"],
        "isolation":isolation,"cases":scopes,
        "model":{
            "signals":"Standard 4h chart OHLC/ATR and recursive SuperTrend, transformed Heikin-Ashi candles for the directional filters, independent RSI/EMA/HMA and current/confirmed CCI trailing levels. Starting indicators use the saved window's first bar; BTC source market and matched ETH interval.",
            "requests":"The two archived lookahead warnings refer to explicit prior-bar [1] values in the same 240-minute series. Every signal-bearing higher-timeframe value equals the independently computed previous closed 4h reference. The authored 30-minute HA close is observational, with no order dependency.",
            "operations":"Every UTC 16:00 bar raises the source session exit edge, next eligible at 20:00 UTC. Scheduled and crossover closes use the original next-open market orders and all modeled executions match the first 15-minute child open. Default fixed one unit and 1,000,000 USDT per symbol. No final unsettled positions.",
            "costs":"The archive omits fees and slippage. A fixed 0.075% fee overlay per side uses the same lots. Results and drawdown are realized and measured in USDT. The benchmark does not include spread, order-book depth or funding.",
        },
        "coverage":[[2708,"Tested · archived Heikin-Ashi and confirmed CCI trail",
                     "Exact Pine v4, 15 matched real market-open closes and all 360 reconstructed indicator decisions and equity marks. Same-resolution prior-frame references resolved. Every market closes flat."]],
        "results":rows,
    })

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
