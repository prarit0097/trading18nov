"""Build the #694 isolated runner input from the verified public FMZ receipts."""

import gzip
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

SYMBOLS = ("BTC", "ETH", "LTC")
END = 1578614400
INPUT_DIGEST = "e6bada4aff24fe5d2a5a2073cb0a299329ce00b44056e80af19fb746931eaf78"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def append_packet(directory, symbol, start, count, expected_hash, detail, rows):
    raw = (directory / f"{symbol}-{start}.json").read_bytes()
    assert digest(raw) == expected_hash
    packet = json.loads(raw)
    assert packet["detail"]["alias"] == symbol + "-USDT"
    assert packet["schema"] == ["time", "open", "high", "low", "close", "vol"]
    assert detail is None or detail == packet["detail"]
    assert not rows or start * 1000 == rows[-1][0] + 60000
    assert len(packet["data"]) == count
    assert [r[0] for r in packet["data"]] == [
        start * 1000 + i * 60000 for i in range(count)
    ]
    rows.extend(packet["data"])
    return packet["detail"]


def main(archive, market_manifest, tail_manifest, directory, output):
    manifest = json.loads(market_manifest.read_bytes())
    tails = json.loads(tail_manifest.read_bytes())
    source = unquote(manifest["archived_document"].split("/blob/", 1)[1])
    with ZipFile(archive) as market:
        raw = market.read("strategies-" + source)
    assert digest(raw) == manifest["archived_sha256"]
    script = raw.decode("utf-8-sig").split("``` python\n", 1)[1].split("```", 1)[0]
    feeds = {}
    for symbol in SYMBOLS:
        rows = []
        detail = None
        receipts = [r for r in manifest["market_receipts"] if r["coin"] == symbol]
        assert len(receipts) == 24
        for part in receipts:
            assert not part["missing"]
            detail = append_packet(
                directory,
                symbol,
                part["from"],
                part["rows"],
                part["sha256"],
                detail,
                rows,
            )
        key = symbol + "_USDT"
        detail = append_packet(
            directory, symbol, END, 1440, tails[key][1], detail, rows
        )
        assert len(rows) == 469440
        feeds[key] = {
            "schema": ["time", "open", "high", "low", "close", "vol"],
            "detail": detail,
            "data": rows,
        }
    prepared = json.dumps(
        {"source": script, "feeds": feeds}, separators=(",", ":")
    ).encode()
    assert digest(prepared) == INPUT_DIGEST
    output.write_bytes(gzip.compress(prepared, compresslevel=4, mtime=0))


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
