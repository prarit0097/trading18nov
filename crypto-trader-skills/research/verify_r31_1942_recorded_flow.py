"""Compare #1942 modeled fill windows against exchange-recorded aggressive flow."""

import argparse
import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile
from fmz_native_round20_880_capture import sha
from stage_r29_4685_native import get

D=Decimal
ZERO=D(0)


def check(result):
    day=result['model']['day']
    filename=f'BTCUSDT-aggTrades-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/{filename}'
    digest,name=get(url+'.CHECKSUM',200).decode().split()
    assert name==filename
    raw=get(url,60_000_000)
    assert sha(raw)==digest
    requests=[]
    for s in result['model']['settled']:
        o=s['order']
        assert o['Status']==1
        requests.append({'order_id':o['Id'],'side':o['Type'],'begin_ms':o['Time'],'end_ms':s['first_terminal']['get_ms'],
                        'limit_price':D(str(o['Price'])),'native_fill_quantity':D(str(o['DealAmount'])),
                        'strict_trade_through_qty':ZERO,'exact_price_aggressive_qty':ZERO,'first_strict_at_ms':None})
    earliest=min(x['begin_ms'] for x in requests)
    latest=max(x['end_ms'] for x in requests)
    seen=0
    last=0
    with ZipFile(io.BytesIO(raw)) as z:
        [member]=z.namelist()
        with z.open(member) as fh:
            for row in csv.reader(io.TextIOWrapper(fh,encoding='utf-8')):
                if not row[0].isdigit(): continue
                seen+=1
                ts=int(row[5]); assert ts>=last
                last=ts
                if not earliest<=ts<=latest: continue
                side=row[6].lower()
                assert side in ('true','false')
                buy_passive=side=='true'
                px,qty=D(row[1]),D(row[2])
                for x in requests:
                    if not x['begin_ms']<=ts<=x['end_ms'] or buy_passive!=(x['side']==0): continue
                    limit=x['limit_price']
                    if px==limit:
                        x['exact_price_aggressive_qty']+=qty
                    elif (buy_passive and px<limit) or (not buy_passive and px>limit):
                        if x['first_strict_at_ms'] is None:x['first_strict_at_ms']=ts
                        x['strict_trade_through_qty']+=qty
    for x in requests:
        x['has_full_size_strict_flow_at_native_fill_deadline']=x['strict_trade_through_qty']>=x['native_fill_quantity']
    return {'day':day,'url':url,'checksum_url':url+'.CHECKSUM','sha256':digest,'compressed_bytes':len(raw),'rows':seen,'orders':requests}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--receipt',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    all_runs=a.receipt.read_bytes()
    data=json.loads(all_runs)
    with ThreadPoolExecutor(max_workers=2) as pool:
        scopes=list(pool.map(check,data['results']))
    obj={'native_receipt_sha256':sha(all_runs),'scopes':scopes,
        'interpretation':'The intersections test independently timed aggressive trades through each original native simulated limit. An unmodified historical book does not retain a queue position for hypothetical orders, and the archived strategy may change later order times under different fills.'}
    a.output.write_text(json.dumps(obj,ensure_ascii=False,default=str)+'\n',encoding='utf-8',newline='\n')
    print([(s['day'],s['rows'],sum(r['has_full_size_strict_flow_at_native_fill_deadline'] for r in s['orders']),len(s['orders'])) for s in scopes],flush=True)


if __name__=='__main__':
    main()
