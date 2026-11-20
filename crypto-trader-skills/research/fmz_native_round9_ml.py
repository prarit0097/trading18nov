"""Stage source-bound Bitfinex spot studies using historical estimator defaults."""

import argparse
import ast
import json
from itertools import pairwise
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_native_round3 import WINDOWS
from research.fmz_native_round5 import replace_once
from research.fmz_native_round6_audit import ROOT, digest
from research.fmz_native_round7 import (
    display_settings,
    file_opening,
    finish,
    header_settings,
    source,
)

STEM = "round9-bitfinex-ml"
WORKER = "fmz_native_round9_ml_worker.py"
WINDOW_STEP = 900_000
CASES = {
    688: (
        "Use the author's SpreadVal=2, its hourly Bitfinex spot records and the source trading branches. Python 3 range replaces xrange. The seeded estimator uses the contemporary historical dual solver.",
        "https://scikit-learn.org/0.21/modules/generated/sklearn.svm.LinearSVC.html",
    ),
    3698: (
        "Preserve the source's rolling training buffer, one-hour sampling and 15-minute base tape. The seeded ten-tree model follows the contemporary pre-0.22 estimator default.",
        "https://scikit-learn.org/0.21/modules/generated/sklearn.ensemble.RandomForestClassifier.html",
    ),
}


def source_port(ident, original):
    code, opening = header_settings(original)
    if ident == 688:
        code = replace_once(code, "xrange(", "range(")
        code = replace_once(
            code, "svm.LinearSVC()", "svm.LinearSVC(dual=True, random_state=0)"
        )
    else:
        code = replace_once(
            code,
            "RandomForestClassifier()",
            "RandomForestClassifier(n_estimators=10, random_state=0, n_jobs=1)",
        )
    ast.parse(code)
    return code, opening


def build_worker(target):
    base = (target / "fmz_native_python_round7_worker.py").read_text(encoding="utf-8")
    code = replace_once(base, "import math\n", "import math\nimport os\n")
    line = 'sys.path.insert(0, str(ROOT / "deps"))\n'
    code = replace_once(
        code,
        line,
        line
        + """sys.path.insert(0, str(ROOT / "r9-ml"))
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
""",
    )
    where = "    requests = []\n"
    code = replace_once(
        code,
        where,
        """    import sklearn
    assert sklearn.__version__ == options["scikit_learn"]
"""
        + where,
    )
    code = code.replace("Binance", "Bitfinex").replace(
        "round7-native-python-", STEM + "-"
    )
    ast.parse(code)
    (target / WORKER).write_text(code, encoding="utf-8", newline="\n")


def stage_feed(work, target, coin, providers):
    parts = []
    for item in providers:
        raw = (work / item["filename"]).read_bytes()
        assert digest(raw) == item["sha256"]
        chart = json.loads(raw)
        assert len(chart["data"]) == item["rows"]
        parts.append(chart)
    early, later = parts
    assert early["detail"] == later["detail"]
    assert early["data"][-1][:2] == later["data"][0][:2]
    rows = early["data"][:-1] + later["data"]
    assert all(b[0] - a[0] == WINDOW_STEP for a, b in pairwise(rows))
    chart = {**later, "data": rows}
    filename = f"round9-bitfinex-{coin}-15m.json"
    payload = json.dumps(chart, separators=(",", ":"), allow_nan=False).encode()
    (target / filename).write_bytes(payload)
    return {
        "coin": coin,
        "symbol": chart["detail"]["symbol"],
        "quote_currency": "USD",
        "base": "15m",
        "period": "1h",
        "base_seconds": WINDOW_STEP // 1000,
        "file": filename,
        "sha256": digest(payload),
        "providers": providers,
    }


def stage(archive, work, public_cache, target):
    catalogue = {
        r["id"]: r
        for r in read(ROOT / "remaining-backtest-round7-coverage.json")["disposition"]
    }
    audit = {
        r["id"]: r
        for r in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
    }
    dependency = read(target / "round9-ml-fixture.json")
    manifest = read(work / "market-manifest.json")
    feeds = {
        coin: stage_feed(
            work, target, coin, [row for row in manifest if row["coin"] == coin]
        )
        for coin in ("BTC", "ETH")
    }
    jobs = []
    with ZipFile(archive) as zipfile:
        for ident, (notes, assumption) in CASES.items():
            item = catalogue[ident]
            raw, original = source(zipfile, item["source"])
            assert digest(raw) == audit[ident]["document_sha256"]
            public = display_settings(public_cache, ident, original)
            assert public["args"] == ({"SpreadVal": 2} if ident == 688 else {})
            code, opening = source_port(ident, original)
            for common in feeds.values():
                for start, (end, _) in WINDOWS.items():
                    feed = {**common, "start": start, "end": end}
                    jobs.append(
                        {
                            "item": {
                                "id": ident,
                                "name": item["name"],
                                "source": item["source"],
                                "source_sha256": digest(raw),
                                "code": code,
                                "args": public["args"],
                            },
                            "feed": feed,
                            "options": {
                                "opening": file_opening(target, feed, opening, ident),
                                "scikit_learn": dependency["sklearn"],
                            },
                            "public": {
                                **public,
                                "estimated_runtime_profile": assumption,
                                "dependency_versions": dependency,
                                "reproducibility_seed": 0,
                            },
                            "note": notes
                            + " BTC/USD is the archived instrument. ETH/USD uses the same USD thresholds as a separate port.",
                        }
                    )
    build_worker(target)
    write(target / (STEM + "-jobs.json"), jobs)
    print(f"Staged {len(jobs)} historical Bitfinex model replays.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("public_cache", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--finish", type=Path)
    options = parser.parse_args()
    if options.finish:
        finish(options.target, options.finish, stem=STEM, worker=WORKER)
    else:
        stage(options.archive, options.work, options.public_cache, options.target)
