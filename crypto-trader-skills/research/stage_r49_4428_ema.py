"""Bind the author's original #4428 EMA research notebook and Binance inputs."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r48_4427_hedge import AUTHOR, reconcile

NOTE='https://www.fmz.com/upload/asset/1510f281f3138cc1e38.ipynb'
PART1='https://www.fmz.com/digest-topic/5294'
PART2='https://www.fmz.com/bbs-topic/5364'
AUTHOR_PAGE='https://www.fmz.com/strategy/195226'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','notebook','csv','output'):
        p.add_argument('--'+k,required=True,type=Path)
    p.add_argument('--archive-cache',type=Path)
    a=p.parse_args()
    [strategy]=[r for r in json.loads(a.catalog.read_bytes())['disposition'] if r['id']==4428]
    with ZipFile(a.archive) as z:
        doc=z.read('strategies-'+unquote(strategy['source'].split('/blob/')[1]))
    assert strategy['pinned_document_sha256']==sha(doc)
    native=doc.decode()
    assert all(v in native for v in (AUTHOR_PAGE,PART1,'Alpha = 0.001','Update_base_price_time_interval = 60','btc_diff'))
    archive=a.notebook.read_bytes()
    assert sha(archive)=='d72cfd3cbb9071afa576d8d03769c7dbf7484931e7359823509b09b279d26afb'
    nb=json.loads(archive)['cells']
    cells={i:''.join(nb[i]['source']) for i in (2,3,4,5,6,16,22)}
    libs=cells[3]
    assert AUTHOR in libs and 'Alpha = 0.05' in cells[16]
    assert 'ewm(alpha=0.05)' in cells[22] and 'commission=0.0005' in cells[16]
    [lst]=ast.parse(cells[2]).body
    symbols=ast.literal_eval(lst.value)
    assert len(symbols)==23 and 'ETH' in symbols and 'BTC' not in symbols
    csvraw=a.csv.read_bytes()
    assert sha(csvraw)=='47dac237f183390ee217aa4ca8245c8cd65873552efc243bdb6f2089d96cb483'
    rows=list(csv.DictReader(io.StringIO(csvraw.decode('utf-8-sig'))))
    assert len(rows)==1500 and sorted(set(rows[0]) - {'0'})==sorted([*symbols,'BTC'])
    with ThreadPoolExecutor(max_workers=8) as e:
        works={s:e.submit(reconcile,s,rows,a.archive_cache) for s in sorted([*symbols,'BTC'])}
        proof=[v.result() for v in works.values()]
    result={'source':{'url':strategy['source'],'archive_sha256':sha(doc),'author_page':AUTHOR_PAGE,'part1':PART1,'part2':PART2,
                      'notebook_url':NOTE,'notebook_sha256':sha(archive),'csv_url':AUTHOR,'csv_sha256':sha(csvraw),
                      'cells':{str(k):sha(v.encode()) for k,v in cells.items()}},
            'alt_symbols':symbols,'no_direct_btc_trade':True,'proof':proof,'source_rows':len(rows)}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(sha(a.output.read_bytes()),sum(x['finalized_exact_matches'] for x in proof),len(proof),flush=True)


if __name__=='__main__':main()
