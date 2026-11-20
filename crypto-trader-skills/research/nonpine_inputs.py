"""Recover checksum-verified Binance data and pinned source for the non-FMZ replay."""

from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

BASE = Path(__file__).resolve().parent
FREQ_ARCHIVE = "https://codeload.github.com/freqtrade/freqtrade-strategies/zip/f3340ce11f5bdf62f598522e64d1f5638eaa13f5"
JESSE_ARCHIVE = "https://codeload.github.com/jesse-ai/example-strategies/zip/7c91e0a37bf62165790120d730442e4f6eb00364"


def verified(path, url, expected):
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return
    with urlopen(url, timeout=60) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"Public input checksum changed: {path.name}")
    path.write_bytes(raw)


def prepare(work):
    work = work.resolve()
    if work.is_relative_to(BASE.parent):
        raise ValueError("Use a scratch folder outside the repository for isolation")
    feeds = work / "binance"
    feeds.mkdir(parents=True, exist_ok=True)
    report = json.loads((BASE / "nonpine_replay.json").read_bytes())
    manifest = report["market_data"]
    jobs = [
        (feeds / name, spec["url"], spec["sha256_or_error"])
        for name, spec in manifest.items()
        if len(spec["sha256_or_error"]) == 64
    ]
    for name, url in (("freq.zip", FREQ_ARCHIVE), ("example.zip", JESSE_ARCHIVE)):
        jobs.append((work / name, url, report["archive_sha256"][name]))
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda args: verified(*args), jobs))
    (feeds / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    snapshot = json.loads((BASE / "nonpine_binance_markets.json").read_bytes())
    for venue, markets in snapshot.items():
        (work / f"{venue}-exchange.json").write_text(
            json.dumps(markets), encoding="utf-8"
        )
    with (BASE / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as f:
        selected = [
            dict(row, id=i)
            for i, row in enumerate(csv.DictReader(f), 1)
            if row["source"] == "freqtrade-strategies"
        ]
    (work / "freq-catalogue.json").write_text(json.dumps(selected), encoding="utf-8")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
