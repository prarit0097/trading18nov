"""Build causal two-second limit evidence for the dated OKEX native replay."""

import gzip
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stage_r21_967_okx_cold_start import BOX, US, sha, source_rows

BASE=BOX/"round21-967-okx-cold-start.json.gz"


def rows(day,label,start,end):
    proof={}
    result=defaultdict(list)
    for local,row in source_rows(day,label,proof):
        sec=local//US
        if start <= sec < end:
            if label=="trades":
                side=row["side"]
                assert side in ("buy","sell")
                qty=float(row["amount"])
                assert qty >= 1
                result[sec].append([local-sec*US,1 if side=="buy" else -1,float(row["price"]),qty])
            else:
                result[sec].append([local-sec*US,float(row["bid_price"]),float(row["ask_price"])])
    return dict(result),proof


def main():
    raw=BASE.read_bytes()
    job=json.loads(gzip.decompress(raw))
    all_results={}
    for day, spec in job["scopes"].items():
        start=spec["start"]+10*3600+50*60
        end=spec["end"]+3
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs={kind:executor.submit(rows,day,kind,start,end) for kind in ("trades","quotes")}
            results={kind:w.result() for kind,w in jobs.items()}
        assert all(results[k][1]["sha256"]==spec["proof"][k]["sha256"] for k in results)
        # Keep all local times and prints in trading seconds. No fill decision is taken here.
        tables={k:v[0] for k,v in results.items()}
        counts={k:sum(map(len,v.values())) for k,v in tables.items()}
        print(day,counts,flush=True)
        all_results[day]={"start":start,"end":end,"tables":tables,"counts":counts}
    pack={"base_sha256":sha(raw),"scopes":all_results}
    compressed=gzip.compress((json.dumps(pack,separators=(",",":"))+"\n").encode(),mtime=0)
    out=BOX/"round21-967-micro-fill-tape.json.gz"
    with out.open("xb") as f:
        f.write(compressed)
    print("micro input",len(compressed),sha(compressed),flush=True)


if __name__=="__main__":
    main()
