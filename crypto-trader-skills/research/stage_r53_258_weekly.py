"""Bind the original JavaScript Dual Thrust source to independently proven dated market tape."""
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
    [row]=[s for s in json.loads(a.catalog.read_bytes())['disposition'] if s['id']==258]
    with ZipFile(a.archive) as archive:
        raw=archive.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert sha(raw)==row['pinned_document_sha256']=='e985ff9ae972153f448b286da948b22e190f7858fa896430934fa7d1f84ef6ba'
    [script]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',raw.decode())
    assert 'exchange.GetName() !== \'Futures_OKCoin\'' in script and '"this_week", "next_week", "quarter"' in script
    assert 'LoopInterval = Math.min(1, LoopInterval)' in script and 'LoopInterval = Math.max(LoopInterval, 1)' in script
    pub=a.author.read_bytes()
    s=pub.decode()
    f=re.search(r'\[\[([\\]+")ContractTypeIdx',s)
    default_form=json.loads(s[f.start():s.index(']]',f.start())+2].replace(f[1],'"'))
    options={x[0]:x[3] for x in default_form}
    assert options.pop('ContractTypeIdx')=='$$$__list__$$$当周|次周|季度'
    assert options.pop('MarginLevelIdx')=='$$$__list__$$$10|20'
    options.update(ContractTypeIdx=0,MarginLevelIdx=0)
    assert options==job['params']
    job.update(source_url=row['source'],source_sha256=sha(script.encode()),archive_sha256=sha(raw),script=script,
               publisher='https://www.fmz.com/strategy/12101',publisher_snapshot_sha256=sha(pub),proven_input_sha256=sha(data))
    a.output.write_bytes(gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    print(sha(a.output.read_bytes()),job['publisher_snapshot_sha256'],flush=True)


if __name__=='__main__':main()
