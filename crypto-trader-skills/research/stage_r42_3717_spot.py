"""Bind FMZ #3717 and stage the first UTC day's Binance spot observations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import request, sha
from stage_r35_197_recorded_depth import fixed

DAY = '2021-08-01'
BEGIN = int(datetime.fromisoformat(DAY).replace(tzinfo=timezone.utc).timestamp())
END = BEGIN + 86_400
MARKET = 'BTCUSDT'
BOOK = 'book_snapshot_25'
LIMIT = 300_000_000


class StreamDigest:
    def __init__(self, stream):
        self.stream = stream
        self.sha = hashlib.sha256()
        self.size = 0

    def read(self, size):
        part = self.stream.read(size)
        self.size += len(part)
        assert self.size <= LIMIT
        self.sha.update(part)
        return part


def rows(channel, proof):
    url = f'https://datasets.tardis.dev/v1/binance/{channel}/2021/08/01/{MARKET}.csv.gz'
    previous = count = 0
    with request(url) as response:
        length = int(response.headers['Content-Length'])
        assert response.status == 200 and 1000 < length <= LIMIT
        stream = StreamDigest(response)
        with gzip.GzipFile(fileobj=stream) as gz:
            fields = gz.readline().strip().split(b',')
            assert fields[:4] == [b'exchange', b'symbol', b'timestamp', b'local_timestamp']
            if channel == BOOK:
                assert len(fields) == 104 and fields[4:8] == [b'asks[0].price', b'asks[0].amount', b'bids[0].price', b'bids[0].amount']
            else:
                assert fields[4:] == [b'id', b'side', b'price', b'amount']
            for row in gz:
                fields = row.strip().split(b',')
                assert fields[:2] == [b'binance', b'BTCUSDT']
                venue, local = map(int, fields[2:4])
                assert local >= previous
                previous = local
                count += 1
                yield max(venue, local), venue, local, fields[4:]
        assert stream.size == length and count > 10_000
    proof.update(url=url, sha256=stream.sha.hexdigest(), raw_bytes=length, raw_rows=count)


def books():
    proof = {}
    # Keep only the latest snapshot independently eligible before each one-second poll.
    pending = None
    output = []
    for eligible, venue, local, raw in rows(BOOK, proof):
        second = (eligible + 999_999) // 1_000_000
        if not BEGIN <= second < END:
            continue
        if pending is not None and second < pending[0]:
            continue
        if pending is not None and second > pending[0]:
            output.append(pending)
            pending = None
        if pending is not None and eligible < pending[1]:
            continue
        pending = (second, eligible, venue, local, raw)
    if pending is not None:
        output.append(pending)
    results = []
    crossed = 0
    for sec, eligible, venue, local, raw in output:
        depth = [fixed(v, 2 if i % 2 == 0 else 8) if v else 0 for i, v in enumerate(raw)]
        assert len(depth) == 100 and all(v >= 0 for v in depth)
        ask, bid = depth[0], depth[2]
        if not 0 < bid < ask or not depth[1] or not depth[3]:
            crossed += 1
            results.append([sec, eligible, venue, local, []])
        else:
            assert access_prices(depth, 0) == sorted(access_prices(depth, 0))
            assert access_prices(depth, 2) == sorted(access_prices(depth, 2), reverse=True)
            results.append([sec, eligible, venue, local, depth])
    proof.update(sampled_polls=len(results), retained_crossed_or_empty=crossed, first=results[0][0], last=results[-1][0])
    return results, proof


def access_prices(depth, at):
    return [p for p in depth[at::4] if p]


def trades():
    proof, data = {}, []
    for eligible, venue, local, raw in rows('trades', proof):
        if BEGIN * 1_000_000 <= eligible < END * 1_000_000:
            identity, side, price, qty = raw
            assert side in (b'buy', b'sell')
            data.append([eligible, int(identity), fixed(price, 2), fixed(qty, 8), int(side == b'buy'), venue, local])
    data.sort(key=lambda row: (row[0], row[1]))
    assert len({r[1] for r in data}) == len(data) > 100_000
    assert all(r[2] > 0 and r[3] > 0 for r in data)
    proof.update(retained=len(data), first_eligible_us=data[0][0], last_eligible_us=data[-1][0])
    return data, proof


def source(catalog, archive):
    [row] = [v for v in json.loads(catalog.read_bytes())['disposition'] if v['id'] == 3717]
    with ZipFile(archive) as z:
        raw = z.read('strategies-' + unquote(row['source'].split('/blob/')[1]))
    assert sha(raw) == row['pinned_document_sha256']
    text = raw.decode()
    [script] = re.findall(r'(?ms)^`{3}[ \t]*python[ \t]*\n(.*?)^`{3}', text)
    [settings] = json.loads(re.search(r'(?m)^exchanges: (.+)$', script)[1])
    assert settings == {'eid':'Binance','currency':'BTC_USDT','balance':1_000_000,'stocks':0,'fee':[.06,.075]}
    overrides = dict(json.loads(re.search(r'(?m)^args: (.+)$', script)[1]))
    params = {**overrides, 'trading_pair':'BTC_USDT', 'price_precision':2, 'amount_precision':5}
    assert all(s in text for s in ('|trading_pair|BTC_USDT|', '|price_precision|2|', '|amount_precision|5|'))
    assert overrides == {'lower_price':30000,'upper_price':50000,'grid_num':200,'trading_per_grid':.1}
    assert 'start: 2021-08-01 00:00:00' in script and 'end: 2021-09-01 00:00:00' in script
    assert 'period: 1m' in script and 'basePeriod: 1m' in script
    return dict(script=script, script_sha256=sha(script.encode()), archive_sha256=sha(raw), source_url=row['source'], params=params, settings=settings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('catalog', 'archive', 'output'):
        parser.add_argument('--'+key,type=Path,required=True)
    args = parser.parse_args()
    job = source(args.catalog, args.archive)
    with ThreadPoolExecutor(max_workers=2) as pool:
        depth, tape = pool.submit(books), pool.submit(trades)
        book, book_proof = depth.result()
        trade, trade_proof = tape.result()
    proof = {BOOK:book_proof, 'trades':trade_proof}
    job.update(book=book, tape=trade, begin=BEGIN, end=END, proof=proof)
    packed = gzip.compress(json.dumps(job, ensure_ascii=False, separators=(',',':')).encode(), compresslevel=4, mtime=0)
    with args.output.open('xb') as out:
        out.write(packed)
    print(len(packed), sha(packed), proof, flush=True)


if __name__ == '__main__':
    main()
