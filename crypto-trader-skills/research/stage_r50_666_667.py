"""Bind the two Levy publications to a previously verified named market tape."""

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

MARKET_SHA = "f03be07ca0c3d6ffad8ef850cb9b1f170d434b9d5892c09d7b04085308e36f2e"
PUBLICATIONS = {666: 119038, 667: 117768}
SETTINGS = {
    "STOP_LOSS": 0.015,
    "TAKE_PROFIT": 0.03,
    "START_SIZE": 1,
    "RISK_LIMIT": 1025,
    "LEVERAGE_RATE": 20,
    "CONTRACT_TYPE": "this_week",
    "DELAY": 30,
    "AMP": 2,
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main(archive, previous_audit, market, public_forms, output):
    tape = market.read_bytes()
    assert sha(tape) == MARKET_SHA
    data = json.loads(gzip.decompress(tape))
    data["market"]["detail"]["marginLevel"] = SETTINGS["LEVERAGE_RATE"]
    cases = json.loads(previous_audit.read_bytes())["disposition"]
    sources = {}
    with ZipFile(archive) as sources_zip:
        for ident, public in PUBLICATIONS.items():
            case = next(r for r in cases if r["id"] == ident)
            revision = unquote(case["source"].split("/blob/", 1)[1])
            raw = sources_zip.read("strategies-" + revision)
            assert sha(raw) == case["pinned_document_sha256"]
            body = (
                raw.decode("utf-8-sig").split("``` python\n", 1)[1].split("```", 1)[0]
            )
            form = (public_forms / f"{public}.html").read_bytes()
            html = form.decode("utf-8")
            param = re.search(r'\[\[([\\]+")STOP_LOSS', html)
            encoded = html[param.start() : html.index("]]", param.start()) + 2]
            settings = {
                row[0]: row[3] for row in json.loads(encoded.replace(param[1], '"'))
            }
            assert settings == SETTINGS
            sources[ident] = {
                "source": body,
                "settings": settings,
                "sha": sha(raw),
                "source_url": case["source"],
                "publication": f"https://www.fmz.com/strategy/{public}",
                "publication_sha256": sha(form),
            }
    outcome = {
        k: data[k]
        for k in ("market", "named_market", "begin_ms", "end_ms", "trade_proof")
    }
    outcome["sources"] = sources
    staged = json.dumps(outcome, ensure_ascii=False, separators=(",", ":")).encode()
    output.write_bytes(gzip.compress(staged, mtime=0))


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
