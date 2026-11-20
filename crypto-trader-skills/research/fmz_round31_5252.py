"""Verify the FMZ #5252 legacy decision-time blocker."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import read,sha256,write

SOURCE="99679cb4be389e97d4420eee05e5a04e1c0eaf43ba672bd1afe2aa64459f6097"
ENGINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
WEEK=7*86400_000

def smooth(rows,col):
    a=math.exp(-1.414*3.14159/4)
    c2=2*a*math.cos(1.414*3.14159/4)
    c3=-a*a
    c1=1-c2-c3
    series=[0,0]
    prior=0
    for bar in rows:
        price=bar[col]
        series.append(c1*(price+prior)/2+c2*series[-1]+c3*series[-2])
        prior=price
    return series[2:]

def verify(case,replayed):
    assert case["market"]==replayed["market"]
    raw=replayed["trade_projection"]
    assert raw==replayed["observation"]
    assert len(raw["diagnostics"])==2
    assert all(d["code"]=="W_LEGACY_SECURITY_LOOKAHEAD" for d in raw["diagnostics"])
    assert replayed["raw"]["exception"][0].startswith("E_LEGACY_VERSION_FEATURE:")
    assert replayed["legacy"]["exception"][0].startswith("E_UNKNOWN_SYMBOL:")
    assert replayed["explicit_state"]["exception"][0].startswith("E_CALL_ARG_NAME:")
    weekly, chart = case["week"], case["chart"]
    assert len(chart)==144 and len(weekly)==8
    short_line,long_line=smooth(weekly,4),smooth(weekly,1)
    zero,traces=[],[]
    p=raw["plots"]
    assert p["scoped HMA length"]==p["scoped entryL"]==[0]*len(chart)
    for i,row in enumerate(chart):
        stamp=row[0]
        j=max(j for j,r in enumerate(weekly) if r[0]<=stamp)
        assert math.isclose(p["scoped short"][i],short_line[j],abs_tol=1e-8)
        assert math.isclose(p["scoped long"][i],long_line[j],abs_tol=1e-8)
        before=short_line[j]<long_line[j]
        causal=j if stamp+4*3600_000>=weekly[j][0]+WEEK else j-1
        after=short_line[causal]<long_line[causal]
        assert before == bool(p["scoped entryS"][i])
        zero.append(after)
        if before!=after:
            traces.append({"chart_open":stamp,"legacy_week_close":weekly[j][0]+WEEK,
                           "legacy_signal":before,"confirmed_signal":after,
                           "legacy_lines":[short_line[j],long_line[j]],
                           "confirmed_lines":[short_line[causal],long_line[causal]]})
    assert traces and all(row["chart_open"]+4*3600_000<row["legacy_week_close"] for row in traces)
    assert len(raw["broker"]["orders"])==1 and not raw["broker"]["trades"]
    legacy_first=next(i for i,v in enumerate(p["scoped entryS"]) if v==1)
    causal_first=next(i for i,v in enumerate(zero) if v)
    assert chart[legacy_first+1][0]==raw["broker"]["orders"][0]["time"]
    assert chart[legacy_first+1][1]==raw["broker"]["orders"][0]["price"]
    return {"market":case["market"],"changed_short_flags":len(traces),"first_change":traces[0],
            "last_change":traces[-1],"first_legacy_order":raw["broker"]["orders"][0],
            "first_confirmed_diagnostic_order_open":chart[causal_first+1][0]}

def main(work,out):
    feed=work/"5252-inputs.json"
    data=read(feed)
    raw=work/"5252-probe.json"
    assert sha256(work/"source-5252.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(item[0]=="PermissionError" for item in isolation.values())
    scoped=[verify(case,replay) for case,replay in zip(data["cases"],read(raw),strict=True)]
    assert [(r["market"],r["changed_short_flags"]) for r in scoped]==[("BTCUSDT",41),("ETHUSDT",100)]
    write(out,{"schema":"FMZ #5252 historical decision-time evidence",
               "source_url":"https://www.fmz.com/strategy/442550",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"raw_sha256":sha256(raw),
               "input_sha256":sha256(feed),"weekly_receipts":data["weekly_receipts"],
               "isolation":isolation,
               "chart_receipts":read(work/"1070-inputs.json")["official_archives"],
               "evidence":scoped,"coverage":[[5252,"Pending · source-confirmed weekly timing needed",
                "The legacy projection supplies the current week's future close. Confirmed weekly values change short decisions on both BTC and ETH. The authored zero-length Hull pathway and two price-less exits remain explicit source semantics."]],
               "results":[]})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
