"""Compare the two official 1m archive versions to authenticated individual prints."""
import math
from pathlib import Path
from datetime import UTC,datetime
import sys
from research.fmz_round7_magnifier import read,write
from research.fmz_round33_355 import trade_tape

def main(directory):
    x=read(directory/"sandbox/3749-feed.json")["markets"]["BTCUSDT"]
    difference=[(a,b) for a,b in zip(x["chart"],x["daily_comparison"],strict=True) if a!=b]
    assert len(difference)==100
    manifests={}
    observed=trade_tape(directory,"BTCUSDT","2023-11-10",[a for a,b in difference],manifests)
    results=[]
    for mon,day in difference:
        events=observed.get(mon[0],[])
        if not events:
            results.append({"t":mon[0],"prints":0,"monthly":mon,"daily":day})
            continue
        ids=[v[0] for v in events]
        assert all(a<b for a,b in zip(ids,ids[1:]))
        px=[q[2] for q in events]
        reconstructed=(px[0],max(px),min(px),px[-1],math.fsum(q[3] for q in events))
        monthly_match=reconstructed[:4]==tuple(mon[1:5]) and math.isclose(reconstructed[4],mon[5],abs_tol=1e-8)
        daily_match=reconstructed[:4]==tuple(day[1:5]) and math.isclose(reconstructed[4],day[5],abs_tol=1e-8)
        results.append({"t":mon[0],"monthly_ok":monthly_match,"daily_ok":daily_match,
                        "prints":len(events),"first":events[0],"last":events[-1],
                        "candles":[mon,day,[mon[0],*reconstructed]],"ids_missing":ids[-1]-ids[0]+1-len(ids)})
    result={"receipt":list(manifests.values()),"resolution":results}
    write(directory/"3749-tape-comparison.json",result)
    for choice in ("monthly_ok","daily_ok"):
        print(choice,sum(v.get(choice,False) for v in results))
    disputed=next(z for z in results if z["t"]==1699629420000)
    print(disputed)
    print("unmatched first",next((z for z in results if not z.get("monthly_ok") and not z.get("daily_ok")),None))
if __name__=="__main__":
    main(Path(sys.argv[1]))
