"""Bind fourth-round native outcomes and unresolved dependencies to the pinned archive."""

import argparse
import hashlib
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.fmz_native_expanded_replay import BLOCKS, PINE_ORDERS
from research.fmz_native_round3 import PENDING

ROOT = Path(__file__).parent
PREVIOUS = ROOT / "remaining-backtest-round3-coverage.json"
FORMULA_BLOCKERS = {
    492: "Inverse Turtle position sizing, TRADE_AGAIN state, and partial lot accounting remain required.",
    1007: "Matched LENGE and percent recovered. Native position-volume comparisons, trailing variables and inverse sizing remain required.",
    1201: "Needs the original Argus Bitcoin news-score signal history.",
    4515: "Public settings remained unavailable. Needs the original scale and limit parameters and intrabar margin semantics.",
    4736: "Public settings remained unavailable. Needs the original martingale inputs and MULTSIG margin and execution model.",
    5779: "Needs tick-level MULTSIG execution and replay of mutable Turtle scaling and order limits.",
    5780: "The archived source contains a conditional opening directive and no complete grid exit.",
}


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def run(scratch, output, reports):
    previous = [r for r in read(PREVIOUS)["disposition"] if r["status"] == PENDING]
    assert len(previous) == 487
    eligible = {r["id"] for r in previous}
    report_index, report_rows = {}, {}
    for report_path in reports:
        payload = report_path.read_bytes()
        source = read(report_path)
        found = Counter(r["id"] for r in source["results"])
        coverage = {r[0]: (r[1], r[2]) for r in source["coverage"]}
        assert coverage.keys() <= eligible and all(c == 6 for c in found.values())
        assert {i for i, value in coverage.items() if value[0].startswith("Tested")} == found.keys()
        report_index[report_path.name] = {"sha256": digest(payload), "tested": len(found), "rows": sum(found.values())}
        for id_, (status, reason) in coverage.items():
            assert id_ not in report_rows
            report_rows[id_] = (report_path.name, status, reason)
    params = read(scratch / "round4" / "native-params" / "receipt.json")
    verified = {r["id"]: r for r in params}
    rows = []
    archive_path = scratch / "fmz.zip"
    with ZipFile(archive_path) as archive:
        for row in previous:
            id_ = row["id"]
            url = row["source"]
            name = unquote(url.split(f"/{FMZ_REF}/", 1)[1])
            raw = archive.read(f"strategies-{FMZ_REF}/{name}")
            document = raw.decode("utf-8")
            blocks = [(language.strip().lower(), code) for language, code in BLOCKS.findall(document)]
            languages = sorted({tag or "(unlabelled)" for tag, _ in blocks})
            real_pine = any(tag in ("pinescript", "pine", "") and PINE_ORDERS.search(code) for tag, code in blocks)
            status = PENDING
            selected = None
            reason = FORMULA_BLOCKERS.get(id_, row["reason"])
            if real_pine:
                assert id_ not in report_rows
                reason = "Archived Pine order calls are present. This ID belongs to Pine review."
            elif id_ in report_rows:
                selected, status, reason = report_rows[id_]
            link = re.findall(r"(?m)^https://www\.fmz\.com/strategy/\d+\s*$", document)
            rows.append({
                "id": id_, "name": row["name"], "source": url, "document_sha256": digest(raw),
                "source_languages": languages, "scope": "pine" if real_pine else "native or formula",
                "strategy_page": link[-1].strip() if link else None, "prior_reason": row["reason"],
                "selected_report": selected, "status": status, "reason": reason,
                **({"public_parameter_check": verified[id_]} if id_ in verified else {}),
            })
    count = Counter(r["scope"] for r in rows)
    tested = sum(r["status"].startswith("Tested") for r in rows)
    write(output, {"baseline": "fd4ad038", "archive_sha256": digest(archive_path.read_bytes()),
                   "source_revision": FMZ_REF, "eligible_status": PENDING, "total": len(rows), "scope": dict(count),
                   "tested": tested, "pending": len(rows) - tested, "reports": report_index, "disposition": rows})
    print(len(rows), "archive dispositions,", tested, "tested,", dict(count))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("reports", nargs="+", type=Path)
    options = parser.parse_args()
    run(options.scratch, options.output, options.reports)
