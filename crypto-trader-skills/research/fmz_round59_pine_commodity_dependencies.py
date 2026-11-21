"""Audit the public source and external histories of four Khizon Pine cases."""

from __future__ import annotations

import argparse
import re
from gzip import decompress
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, sha256

CASES = {
    1013: ("USOIL", "2", False, 2, 0, "https://www.fmz.com/strategy/426474"),
    2248: ("USOIL", "2", True, 2, 2, "https://www.fmz.com/strategy/432892"),
    3845: ("NGAS", "4", True, 2, 2, "https://www.fmz.com/strategy/439065"),
    4021: ("NGAS", "2", False, 2, 2, "https://www.fmz.com/strategy/426558"),
}
FXCM = "https://candledata.fxcorporate.com/"
DUKE = "https://datafeed.dukascopy.com/datafeed/"


def source_receipts(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    items = {r["id"]: r for r in read(baseline)["disposition"] if r["id"] in CASES}
    assert items.keys() == CASES.keys() and all(
        row["status"].startswith("Pending") for row in items.values()
    )
    proof = []
    coverage = []
    with ZipFile(archive) as book:
        for ident, _, doc, digest in documents(book, items):
            symbol, version, header, entries, exits, url = CASES[ident]
            (code,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc
            )
            active = re.sub(r"(?m)^[ \t]*//[^\n]*", "", code)
            assert f"//@version={version}" in code
            assert bool(re.search(r"(?m)^strategy\(", active)) is header
            assert active.count("strategy.entry(") == entries
            assert active.count("strategy.close(") == exits
            frames = re.findall(r"security\('" + symbol + r"', '(D|240)'", active)
            assert frames == ["D", "240"] and "lookahead" not in active
            settings = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    code,
                )
            )
            proof.append(
                {
                    "id": ident,
                    "url": url,
                    "document_sha256": digest,
                    "archived_settings": settings,
                    "pine": int(version),
                    "active_strategy_declaration": header,
                    "authored_entry_calls": entries,
                    "authored_exit_calls": exits,
                    "reference_symbol": symbol,
                    "reference_resolutions": frames,
                }
            )
            reason = (
                f"Both original order gates require {symbol} daily/4h history. The checked FXCM commodity archive paths return 404 and the public Dukascopy alternative returned 429. "
                "An exact provider and session-clock mapping remains missing."
            )
            if not header:
                reason += " The publisher and pinned revision both comment out the only declared strategy header."
            if version == "2":
                reason += " The archived higher-timeframe call also omits a lookahead override."
            coverage.append(
                [ident, "Pending · FMZ commodity historical gate provenance", reason]
            )
    return sorted(proof, key=lambda row: row["id"]), sorted(coverage)


def provider_receipts(root):
    rows = []
    paths = (
        ("m1/EURUSD/2017/29.csv.gz", 200),
        ("m1/EURUSD/2023/30.csv.gz", 200),
        ("H1/EURUSD/2020/1.csv.gz", 404),
        ("m1/USOil/2023/32.csv.gz", 404),
        ("m1/USOil/2023/46.csv.gz", 404),
        ("H1/USOil/2023/32.csv.gz", 404),
        ("H1/USOil/2023/46.csv.gz", 404),
        ("D1/USOil/2023.csv.gz", 404),
        ("D1/NGAS/2023.csv.gz", 404),
        ("m1/NGAS/2023/32.csv.gz", 404),
        ("m1/NGAS/2024/2.csv.gz", 404),
        ("H1/NGAS/2023/32.csv.gz", 404),
        ("H1/NGAS/2024/2.csv.gz", 404),
    )
    for route, code in paths:
        name = root / (route.replace("/", "-") + ".get")
        data = name.read_bytes()
        if code == 200:
            csv = decompress(data)
            assert b"BidOpen" in csv.splitlines()[0] and len(csv.splitlines()) > 5_000
        else:
            assert b"<title>404 Not Found</title>" in data
        rows.append(
            {
                "url": FXCM + route,
                "recorded_http_status": code,
                "response_sha256": sha256(name),
            }
        )
    for route in (
        "LIGHTCMDUSD/2023/10/BID_candles_hour_1.bi5",
        "LIGHTCMDUSD/2023/BID_candles_day_1.bi5",
        "GASCMDUSD/2024/00/BID_candles_hour_1.bi5",
        "GASCMDUSD/2023/BID_candles_day_1.bi5",
    ):
        name = root / route.replace("/", "-")
        assert read(name)["error"].startswith("Too Many Requests.")
        rows.append(
            {
                "url": DUKE + route,
                "recorded_http_status": 429,
                "response_sha256": sha256(name),
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "baseline", "responses", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    sources, coverage = source_receipts(args.archive, args.baseline)
    write(
        args.output,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "source_proofs": sources,
            "http_probes": provider_receipts(args.responses),
            "verification_scope": "Public GET probes from November 21, 2026. A 200 EUR/USD minute response validated the sample endpoint. FXCM commodity 404s cover the attempted files. A Dukascopy 429 establishes unavailability during these probes rather than missing provider history. A replacement CFD would require a documented session and provider-identity sensitivity. The original Pine v2 higher-timeframe confirmation clock cannot be inferred from candle labels.",
            "references": [
                "https://github.com/fxcm/MarketData",
                "https://www.fxcm.com/markets/commodities/",
                "https://www.dukascopy.com/swiss/english/cfd/range-of-markets/cfd-commodities/",
                "https://www.tradingview.com/pine-script-docs/v4/essential/context-switching-the-security-function/",
            ],
            "coverage": coverage,
            "results": [],
        },
    )


if __name__ == "__main__":
    main()
