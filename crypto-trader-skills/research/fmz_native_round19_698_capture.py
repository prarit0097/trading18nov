"""Pin public Binance BTCUSDT data and compact observed ticker states for #698."""

import csv
import gzip
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request, urlopen


CANDLE_URL = (
    "https://data.binance.vision/data/futures/um/daily/klines/"
    "BTCUSDT/1m/BTCUSDT-1m-2021-05-01.zip"
)
TICK_URL = "https://datasets.tardis.dev/v1/binance-futures/trades/2021/05/01/BTCUSDT.csv.gz"
MIDNIGHT_MS = 1_619_827_200_000
SAMPLE_START_MS = MIDNIGHT_MS + 60_000
END_MS = MIDNIGHT_MS + 86_400_000
POLL_MS = 500
MAX_BYTES = 40_000_000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fetch(url, limit):
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
        body = response.read(limit + 1)
        assert response.status == 200 and len(body) <= limit
    return body


def cents(price):
    units, dot, fractional = price.partition(".")
    assert units.isdigit() and all(ch == "0" for ch in fractional[2:]), price
    return int(units) * 100 + int(fractional[:2].ljust(2, "0"))


def candle_envelope():
    raw = fetch(CANDLE_URL, 200_000)
    declared = fetch(CANDLE_URL + ".CHECKSUM", 1000).decode().split()[0]
    assert digest(raw) == declared
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        [name] = archive.namelist()
        assert name == "BTCUSDT-1m-2021-05-01.csv"
        with archive.open(name) as body:
            rows = list(csv.reader(io.TextIOWrapper(body, encoding="utf-8")))
    assert len(rows) == 1440
    for idx, row in enumerate(rows):
        assert int(row[0]) == MIDNIGHT_MS + 60_000 * idx and int(row[6]) == int(row[0]) + 59_999
    extrema = [(cents(v[3]), cents(v[2])) for v in rows]
    return extrema, {"url": CANDLE_URL, "checksum_url": CANDLE_URL + ".CHECKSUM", "sha256": declared, "bars": len(extrema)}


class HashReader:
    def __init__(self, response):
        self.response = response
        self.sha = hashlib.sha256()
        self.size = 0

    def read(self, size):
        chunk = self.response.read(size)
        self.size += len(chunk)
        assert self.size <= MAX_BYTES
        self.sha.update(chunk)
        return chunk


def tape():
    request = Request(TICK_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=35) as response:
        expected = int(response.headers["Content-Length"])
        assert response.status == 200 and 0 < expected <= MAX_BYTES
        stream = HashReader(response)
        poll = SAMPLE_START_MS * 1000
        ending = END_MS * 1000
        prices = []
        minute_extrema = {}
        previous = None
        first = None
        count = 0
        gap_max = 0
        latency_max = 0
        sequence_gaps = 0
        with gzip.GzipFile(fileobj=stream) as gz, io.TextIOWrapper(gz, encoding="utf-8") as text:
            reader = csv.DictReader(text)
            assert reader.fieldnames == [
                "exchange", "symbol", "timestamp", "local_timestamp", "id", "side", "price", "amount"
            ], reader.fieldnames
            for row in reader:
                assert row["exchange"] == "binance-futures" and row["symbol"] == "BTCUSDT"
                timestamp = int(row["timestamp"])
                local = int(row["local_timestamp"])
                price = cents(row["price"])
                trade_id = int(row["id"])
                if first is None:
                    first = [local, timestamp, price, trade_id]
                if previous is not None:
                    assert local >= previous[0]
                    gap_max = max(gap_max, local-previous[0])
                    if trade_id != previous[3] + 1:
                        sequence_gaps += 1
                    while poll < ending and local > poll:
                        prices.append(previous[2])
                        poll += POLL_MS * 1000
                previous = [local, timestamp, price, trade_id]
                latency_max = max(latency_max, local-timestamp)
                if MIDNIGHT_MS <= timestamp//1000 < END_MS:
                    idx = (timestamp//1000-MIDNIGHT_MS)//60_000
                    a,b = minute_extrema.get(idx, (price,price))
                    minute_extrema[idx] = (min(a,price),max(b,price))
                count += 1
        assert stream.size == expected
        assert first[0] <= SAMPLE_START_MS*1000 and previous[0] >= (END_MS-10_000)*1000
        while poll < ending:
            prices.append(previous[2])
            poll += POLL_MS * 1000
        assert len(prices) == (END_MS-SAMPLE_START_MS)//POLL_MS
        return prices, minute_extrema, {
            "url": TICK_URL,
            "raw_file_sha256": stream.sha.hexdigest(),
            "compressed_bytes": expected,
            "trade_events": count,
            "first": first,
            "last": previous,
            "max_local_interarrival_us": gap_max,
            "max_local_minus_exchange_us": latency_max,
            "nonconsecutive_stream_trade_ids": sequence_gaps,
        }


def stage(root, sandbox):
    shard = json.loads((root / "native-round11-scratch/r19-native-public-parameter-proofs.json").read_text(encoding="utf-8"))
    author = next(row for row in shard if row["id"] == 698)
    assert author["args"] == {"leverage":1, "StopGain":0.05,"StopLoss":0.05}
    assert author["still_missing"] == [] and author["preview_chars"] > 70
    ref_name = author["archive_url"].split("/blob/", 1)[1]
    with zipfile.ZipFile(root / "fmz.zip") as archive:
        raw = archive.read("strategies-" + unquote(ref_name))
    assert digest(raw) == author["archive_sha256"]
    [code] = re.findall(r"(?ms)^\x60{3}[ \t]*python[ \t]*\n(.*?)^\x60{3}",raw.decode())
    assert digest(code.encode()) == author["archive_source_sha256"]
    bars, bar_proof = candle_envelope()
    prices, ticks, tick_proof = tape()
    assert len(ticks) == 1440
    mismatches = [idx for idx in range(1440) if ticks[idx] != bars[idx]]
    outside = [idx for idx in range(1440) if ticks[idx][0] < bars[idx][0] or ticks[idx][1] > bars[idx][1]]
    if outside:
        print("Cross-source candle envelope differences",outside[:20], flush=True)
    seed=prices[0]
    low = min(lo for lo, _ in bars)
    high = max(hi for _, hi in bars)
    assert low*100 > seed*95 and high*100 < seed*105
    assert min(prices) >= low and max(prices) <= high
    job = {
        "source":code, "source_sha256":digest(code.encode()), "author":author,
        "inputs":{
            "start_ms":SAMPLE_START_MS, "end_ms":END_MS, "poll_ms":POLL_MS, "prices_cents":prices
        },
        "evidence": {
            "official_candles":bar_proof, "captured_trades":tick_proof,
            "exact_per_minute_extrema_matches":1440-len(mismatches),
            "extrema_mismatch_minute_indices":mismatches,
            "trade_extrema_outside_official_candle_minute_indices":outside,
            "official_low_cents":low, "official_high_cents":high,
        },
    }
    encoded = gzip.compress((json.dumps(job, ensure_ascii=False, separators=(",", ":"))+"\n").encode(),mtime=0)
    out = sandbox / "r19-native-698-ticker-job.json.gz"
    with out.open("xb") as f:
        f.write(encoded)
    print("job SHA-256", digest(encoded), "bytes",len(encoded))
    print("ticker events",tick_proof["trade_events"],"observations",len(prices))
    print("seed, captured min/max, official min/max",seed,min(prices),max(prices),low,high)
    print("exact per-minute extrema matches",1440-len(mismatches),"outside",len(outside))
    print("full compressed trade stream SHA-256",tick_proof["raw_file_sha256"])


if __name__ == "__main__":
    stage(Path(sys.argv[1]), Path(sys.argv[2]))
