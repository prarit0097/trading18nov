"""Stage #3038's exact daily decision chart, hourly underpinning and USD FX."""

import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate,date_ms,raw_ohlcv,verified_archives,write
from research.fmz_round32_trailing_offset import daily_rates

def main(public,fx,work):
    start,end=map(date_ms,("2022-11-21","2023-11-27"))
    rate,fx_sources=daily_rates(fx)
    required=list(range(start,end,86400_000))
    currency={"schemaVersion":1,"pairs":[{"from":"USDT","to":"USD",
                                          "rates":[{"effectiveTime":t,"rate":float(rate[t])} for t in required]}]}
    months=("2022-11","2022-12",*(f"2023-{i:02d}" for i in range(1,12)))
    sources,cases=[],[]
    for market in ("BTCUSDT","ETHUSDT"):
        paths=verified_archives(public,market,"1h",months,sources)
        base=[bar for path in paths for bar in raw_ohlcv(path,3600_000) if start<=bar[0]<end]
        assert [r[0] for r in base]==list(range(start,end,3600_000))
        cases.append({"market":market,"chart":aggregate(base,24),"hour":base[-9*24:]})
    write(work/"3038-inputs.json",{"start":start,"end":end,"cases":cases,"fx":currency,
                                   "fx_receipts":fx_sources,"market_receipts":sources})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
