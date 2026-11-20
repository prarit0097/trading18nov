"""Run the archived OKEx spot grid against historical OKX candles."""

import argparse
import ast
import json
from itertools import pairwise
from pathlib import Path
from zipfile import ZipFile

from research import fmz_native_round7 as native
from research.delta_pinets_catalogue import read, write
from research.fmz_native_round6_audit import ROOT, digest

IDENT = 696
STEM = "round9-okx-archive-grid"
WORKER = "fmz_native_round9_archive_grid_worker.py"
WINDOWS = {
    "2019-10-24": ("2019-10-27", "Archived October 2019"),
    "2019-11-26": ("2019-11-29", "Archived November 2019"),
}


def stage(archive, work, public_cache, target):
    item = next(
        r
        for r in read(ROOT / "remaining-backtest-round7-coverage.json")["disposition"]
        if r["id"] == IDENT
    )
    with ZipFile(archive) as pin:
        document, code = native.source(pin, item["source"])
    assert digest(document) == item["pinned_document_sha256"]
    public = native.display_settings(public_cache, IDENT, code)
    header = ast.get_docstring(ast.parse(code), clean=False)
    assert all(v in header for v in ("period: 1m", '"OKEX"', '"BTC_USDT"'))
    migrated, opening = native.header_settings(code)
    ast.parse(migrated)
    manifest = read(work / "okx-grid-archive-manifest.json")
    jobs = []
    for coin in ("BTC", "ETH"):
        for start, (end, _) in WINDOWS.items():
            providers = [
                r for r in manifest if r["coin"] == coin and r["window"] == start
            ]
            charts = []
            for provider in providers:
                raw = (work / provider["file"]).read_bytes()
                assert digest(raw) == provider["sha256"]
                chart = json.loads(raw)
                assert len(chart["data"]) == provider["rows"]
                charts.append(chart)
            before, after = charts
            assert before["detail"] == after["detail"]
            assert before["data"][-1][:2] == after["data"][0][:2]
            rows = before["data"][:-1] + after["data"]
            assert all(b[0] - a[0] == 60_000 for a, b in pairwise(rows))
            chart = {**after, "data": rows}
            filename = f"round9-okx-{coin}-{start}-1m.json"
            payload = json.dumps(chart, separators=(",", ":"), allow_nan=False).encode()
            (target / filename).write_bytes(payload)
            feed = {
                "coin": coin,
                "symbol": chart["detail"]["symbol"],
                "start": start,
                "end": end,
                "period": "1m",
                "base": "1m",
                "base_seconds": 60,
                "file": filename,
                "sha256": digest(payload),
                "providers": providers,
            }
            jobs.append(
                {
                    "item": {
                        "id": IDENT,
                        "name": item["name"],
                        "source": item["source"],
                        "source_sha256": digest(document),
                        "code": migrated,
                        "args": {},
                    },
                    "feed": feed,
                    "options": {
                        "opening": native.file_opening(target, feed, opening, IDENT)
                    },
                    "public": {
                        **public,
                        "venue_provenance": "https://www.okx.com/learn/okex-rebrands-to-okx",
                        "source_grid_usdt": [5000, 8000],
                    },
                    "note": "Preserve the source grid of 5,000–8,000 USDT, limit-order functions and one-minute OKEx spot settings. Use verified OKX archival tapes on two disjoint samples inside the original July 2019–January 2020 date range. The ETH port uses the same absolute grid.",
                }
            )
    baseline = (target / "fmz_native_python_round7_worker.py").read_text(
        encoding="utf-8"
    )
    worker = baseline.replace("Binance", "OKX").replace(
        "round7-native-python-", STEM + "-"
    )
    ast.parse(worker)
    (target / WORKER).write_text(worker, encoding="utf-8", newline="\n")
    write(target / (STEM + "-jobs.json"), jobs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("public_cache", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--finish", type=Path)
    args = parser.parse_args()
    if args.finish:
        native.WINDOWS = WINDOWS
        native.KEYS = {(coin, start) for coin in ("BTC", "ETH") for start in WINDOWS}
        native.finish(args.target, args.finish, stem=STEM, worker=WORKER)
    else:
        stage(args.archive, args.work, args.public_cache, args.target)
