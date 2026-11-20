"""Stream official Binance trade ZIPs and verify source-defined bracket ordering."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from json import dumps, loads
from math import isclose
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


def scan(job, directory):
    (market, day), rows = job
    name = f"{market}-trades-{day}.zip"
    url = f"https://data.binance.vision/data/futures/um/daily/trades/{market}/{name}"
    cache = directory / f"official-trades-3172-{market}-{day}.json"
    if cache.is_file():
        old = loads(cache.read_bytes())
        assert [r["input"] for r in old["witnesses"]] == sorted(
            rows, key=lambda a: a["time"]
        )
        return old
    maximum = 140 * 1024 * 1024
    with (
        urlopen(url, timeout=45) as stream,
        urlopen(url + ".CHECKSUM", timeout=25) as checksum,
    ):
        raw = stream.read(maximum + 1)
        assert len(raw) <= maximum
        check = checksum.read().decode().split()
    digest = sha256(raw).hexdigest()
    assert check == [digest, name]
    rows = sorted(rows, key=lambda row: row["time"])
    times = [row["time"] for row in rows]
    assert times == sorted(set(times))
    evidence = []
    for row in rows:
        target, stop = (Decimal(str(round(value, 2))) for value in row["bracket"])
        evidence.append(
            {
                "input": row,
                "target": target,
                "stop": stop,
                "count": 0,
                "digest": sha256(),
            }
        )
    with ZipFile(BytesIO(raw)) as archive:
        (entry,) = archive.namelist()
        with archive.open(entry) as data:
            header = next(data)
            assert (
                header.rstrip().lower() == b"id,price,qty,quote_qty,time,is_buyer_maker"
            ), header
            prev_id = prev_time = -1
            j = 0
            for line in data:
                ident, price, _, _, ts, _ = line.split(b",", 5)
                ident, ts = int(ident), int(ts)
                assert ident > prev_id and ts >= prev_time, (
                    name,
                    ident,
                    prev_id,
                    ts,
                    prev_time,
                )
                prev_id, prev_time = ident, ts
                while j < len(times) and ts >= times[j] + 60_000:
                    j += 1
                if j == len(times):
                    break
                if ts < times[j]:
                    continue
                cell = evidence[j]
                p = Decimal(price.decode())
                cell["digest"].update(line)
                cell["count"] += 1
                if "open" not in cell:
                    cell.update(open=p, high=p, low=p, first=[ident, ts, str(p)])
                cell["high"] = max(cell["high"], p)
                cell["low"] = min(cell["low"], p)
                cell["close"] = p
                cell["last"] = [ident, ts, str(p)]
                if "cross" not in cell and (p >= cell["target"] or p <= cell["stop"]):
                    cell["cross"] = [
                        "target" if p >= cell["target"] else "stop",
                        ident,
                        ts,
                        str(p),
                    ]
                    cell["trades_before_cross"] = cell["count"] - 1
    for cell in evidence:
        assert cell["count"] > 1 and "cross" in cell
        cell["raw_minute_sha256"] = cell.pop("digest").hexdigest()
        assert cell["first"][1] <= cell["cross"][2] <= cell["last"][1]
        assert cell["first"][0] <= cell["cross"][1] <= cell["last"][0]
        for key in ("open", "high", "low"):
            assert isclose(
                float(cell[key]), cell["input"][key], rel_tol=0, abs_tol=1e-8
            ), (name, key, cell)
        for key in ("open", "high", "low", "close", "target", "stop"):
            cell[key] = str(cell[key])
    result = {
        "url": url,
        "zip_sha256": digest,
        "zip_bytes": len(raw),
        "witnesses": evidence,
    }
    cache.write_text(
        dumps(result, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return result


def extract(targets_path, directory, output):
    inputs = defaultdict(list)
    for row in loads(targets_path.read_bytes()):
        day = datetime.fromtimestamp(row["time"] / 1000, UTC).date().isoformat()
        inputs[(row["market"], day)].append(row)
    assert all(m in {"BTCUSDT", "ETHUSDT"} for m, _ in inputs)
    directory.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(
            pool.map(lambda job: scan(job, directory), sorted(inputs.items()))
        )
    output.write_text(
        dumps(receipts, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"Verified {len(receipts)} official trade archives and {sum(len(r['witnesses']) for r in receipts)} dual touches."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("targets", "directory", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    extract(args.targets, args.directory, args.output)


if __name__ == "__main__":
    main()
