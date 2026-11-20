"""Stage pinned #4899 ETHUSDT 30m/15m native balance-grid replay inputs."""

import argparse
import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r29_4685_native import archive, get, q, source_parts, to_market, scaled

URL = 'https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E7%86%8A%E8%B5%9A%E5%B8%81%E7%89%9B%E8%B5%9AU%E4%B9%8B%E5%B9%B3%E8%A1%A1%E7%AD%96%E7%95%A5.md'
DOCUMENT = 'b7a03e06e56eb2380e634449c92f453b509c77b8fd8db7ee21324f0d8c4e0f09'
SOURCE = '636ad26ec51bbb067f7efec7d60d61d1f7ee50f40a5264fcde29a2d913c8d27d'
DAYS = ('2021-05-01', '2021-05-19', '2021-05-31')
MONTHS = ('2021-04', '2021-05', '2021-06')
STEP = 15 * 60_000
DAY = 96 * STEP


def day_start(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)



def minute_reference(day):
    label = f'ETHUSDT-1m-{day}.zip'
    url = f'https://data.binance.vision/data/futures/um/daily/klines/ETHUSDT/1m/{label}'
    digest, filename = get(url+'.CHECKSUM', 200).decode().split()
    raw = get(url, 250_000)
    assert filename == label and sha(raw) == digest
    with ZipFile(io.BytesIO(raw)) as z:
        [filename] = z.namelist()
        with z.open(filename) as f:
            rows = to_market([r for r in csv.reader(io.TextIOWrapper(f, encoding='utf-8')) if r[0].isdigit()], 60_000, False)
    assert [r[0] for r in rows] == list(range(day_start(day),day_start(day)+DAY,60_000))
    return {'rows': rows, 'reference': {'url':url, 'sha256':digest, 'checksum_url':url+'.CHECKSUM'}}

def stage():
    definitions = {'swap': ('klines', '15m'), 'index': ('indexPriceKlines', '15m'), 'funding': ('fundingRate', '')}
    with ThreadPoolExecutor(max_workers=12) as p:
        downloaded = {(k,m): p.submit(archive, 'ETH', category, interval,m)
                      for k, (category, interval) in definitions.items() for m in MONTHS}
        observed_minutes = {day: p.submit(minute_reference, day) for day in DAYS}
        q_matches = {(day,k): p.submit(q,'ETH',k,'feed',STEP,day_start(day),day_start(day)+DAY)
                     for day in DAYS for k in definitions}
    scopes = {day: {'begin':day_start(day), 'end':day_start(day)+DAY,'market':{},'trade_minute_reference':observed_minutes[day].result()} for day in DAYS}
    for kind in definitions:
        downloads = [downloaded[kind,m].result() for m in MONTHS]
        rows = [r for items,_ in downloads for r in items]
        data = [[int(r[0]), *([scaled(r[2],100_000_000)]*4), 0] for r in rows] if kind == 'funding' else to_market(rows, STEP, kind == 'swap')
        assert len({r[0] for r in data}) == len(data)
        for day, spec in scopes.items():
            now = spec['begin']
            native, native_ref = q_matches[day,kind].result()
            interval = (8 * 60 * 60_000) if kind == 'funding' else STEP
            canonical = lambda t: round(t / interval) * interval
            market = [r for r in data if now - 16*DAY <= canonical(r[0]) <= now + 2*DAY]
            ours = {r[0]:r for r in market}
            expected = 3 if kind == 'funding' else 96
            comparison = [r for r in native['data'] if now <= r[0] < now+DAY]
            assert len(comparison) == expected and all(r[0] in ours for r in comparison)
            equal = [sum(ours[r[0]][i] == r[i] for r in comparison) for i in range(1,6)]
            difference = max(abs(ours[r[0]][i]-r[i]) for r in comparison for i in range(1,5))
            assert difference <= (1 if kind=='funding' else 0),(day,kind,equal,difference)
            assert [canonical(r[0]) for r in market] == list(range(now-16*DAY,now+2*DAY+1,interval))
            spec['market'][kind] = {'data':market,'detail':native['detail'],'schema':native['schema'],
                'references':{'native':native_ref,'first_four_equal':equal[:4], 'volume_equal':equal[4],
                              'maximum_price_or_rate_scaled_unit_difference':difference,'venue':[ref for _,ref in downloads]}}
            print(day,kind,equal,native['detail'].get('pricePrecision'),flush=True)
    return scopes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--archive',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args = ap.parse_args()
    with ZipFile(args.archive) as pin:
        source=source_parts(pin,'strategies-'+unquote(URL.split('/blob/')[1]),DOCUMENT,SOURCE)
    parameters={'pricePrecision':2,'amountPrecision':3,'linjie':30,'leverage':10}
    assert 'period: 30m' in source and 'basePeriod: 15m' in source and '"balance":100000' in source
    job={'source':source,'source_sha256':SOURCE,'archive_document_sha256':DOCUMENT,'source_url':URL,'parameters':parameters,
         'fees_pct':[0.02,0.04],'starting_cash_USDT':100000,'scope':stage()}
    payload = gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    args.output.write_bytes(payload)
    print(len(payload),sha(payload),flush=True)


if __name__=='__main__':
    main()
