"""Verify and stage all saved-month BTC/USDT candles for the FMZ simulated-tick run."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path
from urllib.parse import urlencode
from zipfile import ZipFile

from fmz_native_round20_880_capture import request, sha
from stage_r42_3717_spot import source, BEGIN

END = BEGIN + 31*86400
LABEL = 'BTCUSDT-1m-2021-08.zip'
ARCHIVE = f'https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/{LABEL}'
PAUSE = tuple(int(datetime(2021,8,13,h,m,tzinfo=timezone.utc).timestamp()) for h,m in ((2,0),(6,30)))


def minutes(a,b):
    return [t*1000 for t in range(a,b,60) if not PAUSE[0]<=t<PAUSE[1]]


def official():
    with request(ARCHIVE+'.CHECKSUM') as r:
        checksum, name = r.read(150).decode().split()
    assert name==LABEL
    with request(ARCHIVE) as r:
        raw = r.read(8_000_000)
    assert sha(raw)==checksum
    data=[]
    exact_volumes=[]
    with ZipFile(io.BytesIO(raw)) as archive:
        [name]=archive.namelist()
        with archive.open(name) as csvf:
            for row in csv.reader(io.TextIOWrapper(csvf,encoding='utf-8')):
                ts=int(row[0])
                expected_close=ts+(59000 if ts==(PAUSE[0]-60)*1000 else 59999)
                assert int(row[6])==expected_close
                data.append([ts,*[int(Decimal(k)*100) for k in row[1:5]]])
                exact_volumes.append(Decimal(row[5]))
    assert [k[0] for k in data]==minutes(BEGIN,END)
    return data,exact_volumes,{'url':ARCHIVE,'sha256':checksum,'rows':len(data)}


def fmz(day, finish):
    fields={'detail':'true','round':'true','feeder':'local','event':'feed','eid':'Binance','depth':5,
            'trades':0,'custom':0,'period':60000,'symbol':'BTC_USDT','from':day,'to':finish-60}
    url='https://q.fmz.com/data/history?'+urlencode(fields)
    with request(url) as r:
        raw=r.read(1_200_000)
    data=json.loads(raw)
    assert 150<len(raw)<1_200_000
    assert data['schema']==['time','open','high','low','close','vol']
    assert [r[0] for r in data['data']]==minutes(day,finish)
    return data,{'url':url,'sha256':sha(raw),'rows':len(data['data'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','output'):
        parser.add_argument('--'+k,type=Path,required=True)
    a=parser.parse_args()
    spec=source(a.catalog,a.archive)
    with ThreadPoolExecutor(max_workers=8) as p:
        official_result=p.submit(official)
        packets=[p.submit(fmz, day, min(END, day+4*86400)) for day in range(BEGIN,END,4*86400)]
        vendor,proof=zip(*(e.result() for e in packets),strict=True)
        ref, volumes, exchange=official_result.result()
    data=[bar for packet in vendor for bar in packet['data']]
    assert all(v['detail']==vendor[0]['detail'] for v in vendor)
    mismatches=[i for i,(f,e) in enumerate(zip(data,ref,strict=True)) if f[:5]!=e]
    if mismatches:
        raise ValueError((len(mismatches),[(data[i],ref[i]) for i in mismatches[:5]]))
    # FMZ encodes volume at 5 decimal places, retaining its own feed's requested round behavior.
    errors=[abs(Decimal(f[5])/100000-v) for f,v in zip(data,volumes,strict=True)]
    exceptions=[(r[0],str(Decimal(r[5])/100000),str(v)) for r,v,e in zip(data,volumes,errors,strict=True) if e>Decimal('.00001')]
    assert exceptions==[(1629354060000,'18.07344','17.87821900')]
    job={**spec,'feed':{'detail':vendor[0]['detail'],'schema':vendor[0]['schema'],'data':data},
         'proof':{'fmz':proof,'binance':exchange,'ohlc_mismatches':0,'volume_exceptions_ms_FMZ_Binance':exceptions,
                  'maximum_absolute_volume_difference_BTC':str(max(errors)),
                  'observed_maintenance_missing_minutes':(PAUSE[1]-PAUSE[0])//60,'maintenance_utc_unix_s':PAUSE,
                  'maintenance_notice':'https://www.binance.com/en/support/announcement/detail/92a9a5bc0129427f8e9928c9b7b09836',
                  'maintenance_complete_notice':'https://www.binance.com/en/support/announcement/detail/3ef1861772a44c67acc2c9f5ec9f87e4'},
         'begin':BEGIN,'end':END}
    payload=gzip.compress(json.dumps(job,separators=(',',':')).encode(),compresslevel=5,mtime=0)
    with a.output.open('xb') as f:f.write(payload)
    print(len(payload),sha(payload),job['proof'],flush=True)


if __name__=='__main__':
    main()
