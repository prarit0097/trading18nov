"""Stage a bounded native replay of the archived weekly Donchian allocator."""

import argparse
import ast
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_native_round5 import replace_once
from research.fmz_native_round6_audit import BASE, ROOT, digest
from research.fmz_native_round7 import display_settings, file_opening, finish, source

IDENT = 5670
STEM = "round7-multiframe"
WORKER = "fmz_native_round7_multiframe_worker.py"
BASE_WORKER = "fmz_native_python_round7_worker.py"


def worker_text(original):
    updated = replace_once(
        original,
        "import hashlib\n",
        "from bisect import bisect_right\nimport hashlib\n",
    )
    original_getter = '        for name in ("GetTicker", "GetRecords"):\n'
    updated = replace_once(
        updated,
        original_getter,
        """        daily_feed = options["daily"]
        raw_days = (ROOT / daily_feed["file"]).read_bytes()
        assert hashlib.sha256(raw_days).hexdigest() == daily_feed["sha256"]
        daily = json.loads(raw_days)
        detail = daily["detail"]
        assert detail["symbol"] == feed["symbol"]
        quote = 10 ** detail["quotePrecision"]
        scale = 10 ** detail["basePrecision"]
        rows = [dict(Time=t, Open=o/quote, High=h/quote, Low=l/quote, Close=c/quote, Volume=v/scale)
                for t, o, h, l, c, v, *_ in daily["data"]]
        endings = [row["Time"] + 86400000 for row in rows]
        assert all(b-a == 86400000 for a,b in zip(endings, endings[1:]))
        assert bisect_right(endings, begin) > 20 * 7
        original_records = venue.GetRecords
        cached_day, cache = 0, []

        def records(period=None):
            nonlocal cached_day, cache
            if period != runtime["PERIOD_D1"]:
                return original_records() if period is None else original_records(period)
            end_index = bisect_right(endings, unix_ns() // 1_000_000)
            if end_index != cached_day:
                cached_day = end_index
                cache = rows[max(0, end_index - 2000):end_index]
            return cache

        venue.GetRecords = records
"""
        + original_getter,
    )
    updated = updated.replace("round7-native-python-", STEM + "-")
    ast.parse(updated)
    return updated


def stage(archive, target, market, work):
    catalogue = next(r for r in read(BASE)["disposition"] if r["id"] == IDENT)
    matched = next(
        row
        for row in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
        if row["id"] == IDENT
    )
    with ZipFile(archive) as pinned:
        raw, original = source(pinned, catalogue["source"])
    assert digest(raw) == matched["document_sha256"]
    public = display_settings(work, IDENT, original)
    assert public["args"] == {}
    code = replace_once(original, "Sleep(1000*60)", "Sleep(1000*60*15)")
    meta = {
        "id": IDENT,
        "name": catalogue["name"],
        "source": catalogue["source"],
        "source_sha256": digest(raw),
        "code": code,
        "args": {},
    }
    jobs = []
    for scenario in read(ROOT / "fmz-native-extra-round6.json")["snapshots"]:
        if scenario["id"] != 4345:
            continue
        original_feed = scenario["feed"]
        feed = {key: value for key, value in original_feed.items() if key != "daily"}
        for receipt in (feed, original_feed["daily"]):
            content = (market / receipt["file"]).read_bytes()
            assert digest(content) == receipt["sha256"]
            staged = target / receipt["file"]
            if staged.exists():
                assert digest(staged.read_bytes()) == receipt["sha256"]
            else:
                staged.write_bytes(content)
        jobs.append(
            {
                "item": meta,
                "feed": feed,
                "options": {
                    "opening": file_opening(target, feed, {}, IDENT),
                    "daily": original_feed["daily"],
                },
                "public": public,
                "note": "Preserve the source's seven-bar composition and hourly order reference. Use completed daily bars and sample every 15-minute base bar for this explicit historical variant.",
            }
        )
    assert len(jobs) == 4
    original_worker = (target / BASE_WORKER).read_text(encoding="utf-8")
    (target / WORKER).write_text(
        worker_text(original_worker), encoding="utf-8", newline="\n"
    )
    write(target / f"{STEM}-jobs.json", jobs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("market", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("--finish", type=Path)
    options = parser.parse_args()
    if options.finish:
        finish(options.target, options.finish, stem=STEM, worker=WORKER)
    else:
        stage(options.archive, options.target, options.market, options.work)
