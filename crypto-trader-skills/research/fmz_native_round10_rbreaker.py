"""Study the archived R-Breaker through a documented historical spot adapter."""

import argparse
import ast
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_native_round5 import replace_once
from research.fmz_native_round6_audit import ROOT, digest
from research.fmz_native_round7 import (
    file_opening,
    finish,
    legacy_python,
    source,
    template,
)

IDENT = 706
STEM = "round10-rbreaker-clock"
WORKER = "fmz_native_round10_rbreaker_clock_worker.py"


def stage(archive, public_cache, target):
    entry = next(
        row
        for row in read(ROOT / "remaining-backtest-round7-coverage.json")["disposition"]
        if row["id"] == IDENT
    )
    with ZipFile(archive) as pinned:
        document, original = source(pinned, entry["source"])
        library_code, info = template(pinned, public_cache)
    assert digest(document) == entry["pinned_document_sha256"]
    assert all(
        name in library_code for name in ("ext.Buy", "ext.Sell", "ext.GetAccount")
    )
    assert (
        target / "round7-native-spot-library.py"
    ).read_bytes() == library_code.encode()
    code = legacy_python(original)
    offset = code.index("\ndef main():")
    code = code[:offset] + replace_once(code[offset:], "Sleep(1000)", "Sleep(60000)")
    ast.parse(code)
    jobs = []
    for job in read(target / "round5-native-python-jobs.json"):
        if job["item"]["id"] != 472:
            continue
        feed = job["feed"]
        assert feed["period"] == "1h"
        jobs.append(
            {
                "item": {
                    "id": IDENT,
                    "name": entry["name"],
                    "source": entry["source"],
                    "source_sha256": digest(document),
                    "code": code,
                    "args": {},
                },
                "feed": feed,
                "options": {
                    "opening": file_opening(target, feed, {}, IDENT),
                    "template": info,
                    "empty_state": True,
                },
                "public": {
                    "archived_calculation": {
                        "pivot_lookback": 2,
                        "filter_interval": "30m",
                    },
                    "adapter_assumption": "The compatible public spot library supplies the original ext interface. The source does not name the exact linked library or an original chart interval.",
                },
                "note": "Labeled R-Breaker study with a 1h chart and 30m source filter. Sample its outer decisions once per minute. Preserve the archived order branches and use the pinned compatible FMZ spot template for its unbound ext interface. Derive the obsolete minimum-quantity call from the input market metadata.",
            }
        )
    assert len(jobs) == 4
    original_worker = (target / "fmz_native_python_round7_worker.py").read_text(
        encoding="utf-8"
    )
    marker = '        venue = runtime["exchange"]\n'
    worker = replace_once(
        original_worker,
        marker,
        marker
        + """        minimum = history["detail"]["minQty"]
        assert 0 < minimum
        venue.GetMinStock = lambda: minimum
""",
    )
    replay_marker = "        stopped = False\n"
    worker = replace_once(
        worker,
        replay_marker,
        """        guarded_venue = {}
        for name in ("Buy", "CancelOrder", "GetAccount", "GetOrders", "Sell"):
            call = getattr(venue, name)
            guarded_venue[name] = call

            def cutoff(*args, call=call, **kwargs):
                if unix_ns() // 1_000_000 >= end - 10_000:
                    raise ReplayEnd()
                return call(*args, **kwargs)

            setattr(venue, name, cutoff)
"""
        + replay_marker,
    )
    stop_marker = "        except ReplayEnd:\n            stopped = True\n"
    worker = replace_once(
        worker,
        stop_marker,
        stop_marker
        + """        finally:
            for name, original in guarded_venue.items():
                setattr(venue, name, original)
""",
    )
    worker = worker.replace("round7-native-python-", STEM + "-")
    ast.parse(worker)
    (target / WORKER).write_text(worker, encoding="utf-8", newline="\n")
    write(target / (STEM + "-jobs.json"), jobs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("public_cache", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--finish", type=Path)
    args = parser.parse_args()
    if args.finish:
        finish(args.target, args.finish, stem=STEM, worker=WORKER)
    else:
        stage(args.archive, args.public_cache, args.target)
