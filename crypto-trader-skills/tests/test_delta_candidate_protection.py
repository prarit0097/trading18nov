from decimal import Decimal as D
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from crypto_skills.delta_candidate_exit import timed_exit
from crypto_skills.delta_candidate_protection import ProtectiveArchive


class ProtectiveArchiveTests(unittest.TestCase):
    def test_modeled_stop_uses_adverse_executable_book_and_verified_funding(self):
        identity = dict(version='test',evidence_sha256='frozen')
        minute = 300_000_000
        header = dict(schema=1,identity=identity,symbols=['ETHUSD'],stream_id='one',first_receipt_ms=301020)
        rows = [
            ['candle',0,301100000,301150,minute,'100','101','99.5','100'],
            ['candle',0,303100000,303150,minute,'100','101','98.6','98.8'],
        ]
        for at, bid in ((301,'99.2'),(301.5,'98.8'),(302,'98.6'),(302.5,'98.7'),
                        (303,'98.8'),(303.5,'98.9'),(304,'98.8')):
            stamp = int(at*1_000_000)
            rows.append(['book',0,stamp,int(at*1000)+20,stamp,[[bid,'3']],['99.9','3']])
        trade = dict(entry_price='100',first_fill_at=4,filled=3,stop='99',target='102',
                     contract_value='1',entry_fee_rate='.001')
        marks = [dict(time=t,open='100',close='100',low='98.6' if t==300 else '99.5',high='101')
                 for t in range(0,660,60)]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            day = root/'1970-01-01'
            day.mkdir()
            file = day/'301020-window.jsonl.gz'
            with gzip.open(file,'wt',encoding='utf-8') as stream:
                for item in [header,*sorted(rows,key=lambda row:row[3])]:
                    stream.write(json.dumps(item)+'\n')
            archive = ProtectiveArchive(root,identity,cutoff=900)
            books = lambda touch, opened, deadline, stop, target: archive.prove(
                'ETHUSD',touch,opened,deadline,stop,target)
            result = timed_exit(trade,marks,[],exit_fee_rate='.001',funding_usd=None,
                                protective_books=books,zero_funding_through=lambda t:t==304)
            self.assertEqual(result['status'],'modeled_exit')
            self.assertEqual(result['trigger_type'],'stop_loss')
            self.assertEqual(D(result['exit_price']),D('98.6'))
            self.assertEqual(result['close_time'],304)
            self.assertEqual(D(result['net_usd']),D('-4.7958'))
            unknown = timed_exit(trade,marks,[],exit_fee_rate='.001',funding_usd='0',
                                 protective_books=books,zero_funding_through=lambda t:False)
            self.assertEqual(unknown['status'],'protective_exit_unresolved')
            with gzip.open(file,'wt',encoding='utf-8') as stream:
                for item in [header,*sorted(rows,key=lambda row:row[3])]:
                    if isinstance(item,list) and item[0]=='book' and item[2]==302000000:
                        item[5][0][1]='2'
                    stream.write(json.dumps(item)+'\n')
            thin = timed_exit(trade,marks,[],exit_fee_rate='.001',funding_usd='0',
                              protective_books=books,zero_funding_through=lambda t:True)
            self.assertEqual(thin['status'],'protective_exit_unresolved')
            marks[5]['high']='103'
            ambiguous = timed_exit(trade,marks,[],exit_fee_rate='.001',funding_usd='0',
                                   protective_books=books,zero_funding_through=lambda t:True)
            self.assertEqual(ambiguous['status'],'protective_exit_unresolved')
