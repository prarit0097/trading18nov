"""Prepare original published one-sided grid with the proven named weekly inverse data."""
import argparse
import gzip
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('catalog','archive','author','proven-input','output'):
        parser.add_argument('--'+option,type=Path,required=True)
    a=parser.parse_args()
    data=a.proven_input.read_bytes()
    assert sha(data)=='f03be07ca0c3d6ffad8ef850cb9b1f170d434b9d5892c09d7b04085308e36f2e'
    job=json.loads(gzip.decompress(data))
    [row]=[s for s in json.loads(a.catalog.read_bytes())['disposition'] if s['id']==5193]
    with ZipFile(a.archive) as archive:
        raw=archive.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert sha(raw)==row['pinned_document_sha256']
    [script]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',raw.decode())
    assert 'if (FirstPriceAuto) {' in script and '"this_week", "next_week", "quarter"' in script
    pub=a.author.read_bytes()
    s=pub.decode()
    f=re.search(r'\[\[([\\]+")ContractTypeIdx',s)
    form=re.sub(r'(\\+)(?=")',lambda m:'\\'*(len(m[1])>>2),s[f.start():f.start()+14000])
    author,end=json.JSONDecoder().raw_decode(form)
    fields=[item for item in author if not item[0].startswith('$$$__cmd__$$$')]
    options={x[0].split('@')[0]:(0 if str(x[3]).startswith('$$$__list__$$$') else x[3]) for x in fields}
    assert len(options)==26 and options['FirstPrice']==100 and options['AllNum']==10 and options['PriceGrid']==1
    assert all(options[k]==1 for k in ('AmountOnce','BAmountOnce','SAmountOnce'))
    assert options['ContractTypeIdx']==options['MarginLevelIdx']==options['OpType']==options['AmountType']==0
    job.update(source_url=row['source'],source_sha256=sha(script.encode()),archive_sha256=sha(raw),script=script,
               publisher='https://www.fmz.com/strategy/8474',publisher_snapshot_sha256=sha(pub),params=options,
               provenance_input_sha256=sha(data),initial_wallet_BTC=2)
    a.output.write_bytes(gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    print(sha(a.output.read_bytes()),job['publisher_snapshot_sha256'],flush=True)


if __name__=='__main__':main()
