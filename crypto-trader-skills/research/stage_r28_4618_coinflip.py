"""Bind archived #4618 settings to checked direct BitMEX XBTUSD samples."""

import argparse
import gzip
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r26_2401_bitmex_vix import quotes

SOURCE="https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E6%8A%9B%E7%A1%AC%E5%B8%81%E7%AD%96%E7%95%A5.md"
MEMBER="strategies-7853bb2bf262c4567ac238d3552d97f0e50cb801/\u629b\u786c\u5e01\u7b56\u7565.md"
SOURCE_SHA="e5423abddbd71628bf8306eb97e2ad53d88148a31a6e2b671a198f8fbd18aaef"
DOC_SHA="c8201a549921c32577eb6ffe35b9ed789e3a3e883e58a05aad3cb15d285d70b4"
TAPE_SHA="370b7f8b9ccadc69b40ba6d0d85fa1fa61f771b0770cd236f51799d210436036"
SEEDS=(1,42,20201120)


def derive(day,spec):
    times=[r[0] for r in spec['samples']]
    assert times==list(range(spec['begin'],spec['end']+1,5)) and len(times)==5761
    horizon,receipt=quotes(day,times)
    assert receipt==spec['captures']['quotes']
    metrics=[]
    for sampled, q in zip(spec['samples'],horizon,strict=True):
        assert q[:6]==sampled[7:13]
        metrics.append(q[6:])
    return {'start':spec['begin'],'end':spec['end'],'today':spec['today'],'tape':spec['samples'],'quote_horizons':metrics,
        'capture_receipts':spec['captures'],'full_day_ohlc':spec['daily_exchange'],'funding':spec['funding_near_settlement']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('archive','tape','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    with ZipFile(a.archive) as z:
        md=z.read(MEMBER)
    [source]=re.findall(r'(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}',md.decode())
    assert sha(md)==DOC_SHA and sha(source.encode())==SOURCE_SHA
    assert all(x in source for x in ('period: 15m','basePeriod: 5m','Futures_BitMEX','"fee":[0.008,0.1]','args: [["st",0.1]]'))
    assert all(x in md.decode() for x in ('|tp_first|0.03|','|trailing_tp|0.01|','|st|0.05|'))
    raw=a.tape.read_bytes()
    assert sha(raw)==TAPE_SHA
    tape=json.loads(gzip.decompress(raw))['scenarios']
    assert list(tape)==['2020-02-01','2020-08-01']
    with ThreadPoolExecutor(max_workers=2) as p:
        tasks={d:p.submit(derive,d,s) for d,s in tape.items()}
        scopes={d:t.result() for d,t in tasks.items()}
    job={'source':source,'source_url':SOURCE,'source_sha256':SOURCE_SHA,'archive_sha256':DOC_SHA,'r20_capture_sha256':TAPE_SHA,
        'params':{'tp_first':0.03,'trailing_tp':0.01,'st':0.1},'published_fees_pct':[0.008,0.1],
        'cash_btc':'0.001','leverage':1,'interval_sec':5,'quote_latency_us':0,'depth_bound_window_us':100000,
        'seeds':SEEDS,'scopes':scopes}
    out=gzip.compress((json.dumps(job,ensure_ascii=False,separators=(',',':'))+'\n').encode(),mtime=0)
    a.output.write_bytes(out)
    print(len(out),sha(out))


if __name__=='__main__':
    main()
