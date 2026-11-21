"""Stage the two recorded USD-M tapes used by the #5773 compatibility check."""

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main(document, output):
    raw = document.read_bytes()
    fence = chr(96) * 3
    (source,) = re.findall(r"(?ms)^" + fence + r" javascript[^\n]*\n(.*?)^" + fence, raw.decode())
    start, end = 1795089600, 1795089660
    result = {"source": source, "source_sha256": digest(source.encode()), "document_sha256": digest(raw),
              "start": start, "end": end, "feeds": {}, "witness": {}}
    for coin in ("BTC", "ETH"):
        symbol = f"{coin}_USDT.swap"
        pieces, proof = [], []
        for low, high in ((start - 10005, start - 6000), (start - 6000, start - 3000), (start - 3000, end + 5)):
            query = {"detail": "true", "round": "true", "feeder": "local", "event": "feed", "eid": "Futures_Binance",
                     "depth": 10, "trades": 1, "custom": 0, "period": 1000, "symbol": symbol, "from": low, "to": high}
            url = "https://q.fmz.com/data/history?" + urlencode(query)
            with urlopen(url, timeout=45) as response:
                body = response.read(49_000_001)
            assert 0 < len(body) <= 49_000_000
            feed = json.loads(body)
            assert feed["schema"] == ["time", "asks", "bids", "close", "vol", "position", "trades"]
            assert feed["detail"]["symbol"] == symbol
            rows = [row for row in feed["data"] if low * 1000 <= row[0] < high * 1000]
            assert rows[0][0] < (low + 5) * 1000 and rows[-1][0] > (high - 5) * 1000
            pieces.extend(rows)
            proof.append([url, len(rows), digest(json.dumps(rows, separators=(",", ":")).encode())])
        assert all(a[0] <= b[0] for a, b in zip(pieces, pieces[1:]))
        result["feeds"][coin] = {"data": pieces, "schema": feed["schema"], "detail": feed["detail"]}
        result["witness"][coin] = proof
    output.write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode(),
                                     compresslevel=2, mtime=0))


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
