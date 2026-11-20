"""Join alternate non-FMZ replays to the frozen unresolved catalogue IDs."""

from collections import Counter
import json
import math
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def finish(work, output):
    baseline = read(BASE / "remaining-backtest-coverage.json")
    targets = {
        d["id"]: d
        for d in baseline["disposition"]
        if d["id"] > 5807 and not d["status"].startswith("Tested")
    }
    assert len(targets) == 159
    deribit = read(work / "round2/deribit-out.json")
    results = {r["id"]: r for r in deribit["cases"]}
    outputs = [
        work / "jesse-round2-out.jsonl",
        *sorted(work.glob("freq-round2*-out.jsonl")),
        work / "round2/legacy-out.jsonl",
        work / "round2/hummingbot-out.jsonl",
    ]
    for path in outputs:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["id"] not in results or row.get("results"):
                results[row["id"]] = row
    assert results.keys() <= targets.keys()
    rows = []
    coverage = []
    for ident, item in sorted(targets.items()):
        data = results.get(ident, {})
        if detail := data.get("results"):
            assert len(detail) == 6 and {x["period"] for x in detail} == {
                "Reference",
                "Later",
            }, ident
            for row in detail:
                assert row["id"] == ident and math.isclose(
                    row["gross"] - row["fees"], row["after_fees"], abs_tol=1e-7
                ), ident
                assert math.isclose(
                    row["after_fees"] + row.get("funding", 0) - row["execution"],
                    row["net"],
                    abs_tol=1e-7,
                ), ident
            group = detail[0]["group"]
            status = (
                f"Tested · {group}"
                if any(x["trades"] for x in detail)
                else "Tested · no closes"
            )
            message = (
                f"{group}. {detail[0].get('source_adaptation', detail[0]['exit'])}"
            )
            rows.extend(detail)
        elif detail := data.get("reason"):
            status, message = "Round 2 dependency or replay failure", detail
        elif ident == 5863:
            status, message = (
                "Round 2 bounded runtime",
                "Removing the obsolete NumPy import allowed FOttStrategy to start, but its iterative OTT callback exhausted the isolated run time before any complete ledger was produced.",
            )
        else:
            status, message = item["status"], item["reason"]
        coverage.append([ident, status, message])
    outcome = dict(
        coverage=coverage,
        rows=rows,
        settings={
            "source_checkpoint": "cb4745c",
            "periods_ist": {
                "Reference": ["2026-09-23", "2026-10-21"],
                "Later": ["2026-10-21", "2026-11-04"],
            },
        },
        deribit_pages=deribit["inputs"],
        deribit_evidence={
            x["id"]: {k: x[k] for k in ("evidence", "trade_ids") if k in x}
            for x in deribit["cases"]
        },
        ethbtc_inputs=read(work / "binance/ethbtc/manifest.json"),
    )
    output.write_text(
        json.dumps(outcome, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    print(Counter(c[1] for c in coverage), len(rows), "rows")


if __name__ == "__main__":
    finish(Path(sys.argv[1]), Path(sys.argv[2]))
