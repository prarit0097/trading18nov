"""Bind the distinct Python FMZ LeeksReaper port to the validated Binance spot capture."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha

MARKET_SHA='a27dd0dbaeea95cf7919bb96b26376db16c165d408316e78d0da57e3311cd845'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','market','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    [row]=[r for r in json.loads(a.catalog.read_bytes())['disposition'] if r['id']==5093]
    with ZipFile(a.archive) as z:
        raw=z.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert sha(raw)==row['pinned_document_sha256']
    text=raw.decode()
    [code]=re.findall(r'(?ms)^`{3}[ \t]*python[ \t]*\n(.*?)^`{3}',text)
    [settings]=json.loads(re.search(r'(?m)^exchanges: (.+)$',code)[1])
    assert settings=={'eid':'Binance','currency':'BTC_USDT','stocks':0,'fee':[0,0]}
    settings_check=('start: 2019-09-05 00:00:00','end: 2019-09-05 22:00:00','period: 1h','basePeriod: 1h','mode: 1','Sleep(400)','Sleep(TickInterval)')
    assert all(x in code for x in settings_check)
    pms={'BurstThresholdPct':5e-05,'BurstThresholdVol':10,'MinStock':.1,'CalcNetInterval':60,'BalanceTimeout':10000,'TickInterval':280}
    for k,p in pms.items():
        found=re.search(r'^\|'+k+r'\|([^|]+)\|',text,re.M)[1]
        assert float(found)==p
    market=sha(a.market.read_bytes())
    assert market==MARKET_SHA
    source={'script':code,'source_url':row['source'],'source_sha256':sha(code.encode()),'archive_sha256':sha(raw),'market_sha256':market,
            'publisher':'https://www.fmz.com/strategy/265827','settings':settings,'params':pms,'saved_date':'2019-09-05','compared_date':'2019-09-01'}
    with a.output.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(source,f,ensure_ascii=False,separators=(',',':'))
    print(sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
