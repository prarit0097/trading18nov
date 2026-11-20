"""Prepare exact FMZ #2708 January and February USD-M inputs."""

import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate,date_ms,raw_ohlcv,verified_archives,write

def main(public,work):
    first,last=map(date_ms,("2024-01-06","2024-02-05"))
    sources,cases=[],[]
    for market in ("BTCUSDT","ETHUSDT"):
        paths=verified_archives(public,market,"15m",("2024-01","2024-02"),sources)
        base=[bar for path in paths for bar in raw_ohlcv(path,900_000) if first<=bar[0]<last]
        assert [r[0] for r in base]==list(range(first,last,900_000))
        cases.append({"market":market,"base":base,"chart":aggregate(base,16),"half":aggregate(base,2)})
    write(work/"2708-inputs.json",{"cases":cases,"source_files":sources})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
