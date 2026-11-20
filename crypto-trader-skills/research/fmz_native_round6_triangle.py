"""Verify archived three-leg FMZ entry gates on synchronized Binance quotes."""

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.fmz_native_expanded_replay import BLOCKS
from research.fmz_native_round6_audit import BASE, ROOT, digest
from research.fmz_native_round6_replay import public_settings
from research.nonpine_round4_basis import DATES, SECOND, snapshots
from research.nonpine_round4_metrics import metrics

IDENT = 1203
NOTES = (
    "Replays the archived BTC/USDT, LTC/USDT and LTC/BTC triangle with Binance "
    "as a venue substitution for OKEX, with matched Q3 and original 0.15% fee comparisons. "
    "Neither source gate passed on either sampled window."
)


def margins(btc, ltc, cross, fee):
    forward_cost = btc[2] * cross[2]
    reverse_value = btc[1] * cross[1]
    return (
        ltc[1] - forward_cost - fee * (2 * ltc[1] + forward_cost),
        reverse_value - ltc[2] - fee * (2 * reverse_value + ltc[2]),
    )


def quote_check(updates, start, end, fee, notional):
    current = [None] * len(updates)
    observed = 0
    largest = [float("-inf"), float("-inf")]
    for at in range(start - 2, end + 1):
        current = [
            grid.get(at, quote) for grid, quote in zip(updates, current, strict=True)
        ]
        if at < start or any(q is None for q in current):
            continue
        times = [q[0] for q in current]
        if at * SECOND - min(times) > 2 * SECOND or max(times) - min(times) > 500_000:
            continue
        observed += 1
        [fwd, rev] = [notional * gap for gap in margins(*current, fee)]
        largest = [max(largest[0], fwd), max(largest[1], rev)]
    assert observed >= 1000, observed
    assert max(largest) <= 0, (
        "An entry passed. Need a complete three-leg accounting model."
    )
    return {"aligned_samples": observed, "maximum_source_margins_usdt": largest}


def run(archive, quotes, work, output):
    strategy = next(r for r in read(BASE)["disposition"] if r["id"] == IDENT)
    check = next(
        r
        for r in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
        if r["id"] == IDENT
    )
    url = strategy["source"]
    with ZipFile(archive) as pinned:
        raw = pinned.read(f"strategies-{FMZ_REF}/{unquote(url.rsplit('/', 1)[1])}")
        assert digest(raw) == check["document_sha256"]
    [source] = [
        code
        for label, code in BLOCKS.findall(raw.decode("utf-8"))
        if label.strip() == "javascript"
    ]
    [page] = re.findall(
        r"(?m)^https://www\.fmz\.com/strategy/\d+\s*$", raw.decode("utf-8")
    )
    params = public_settings(
        work / "fmz-param-1203.html", {"code": source, "parameter_page": page.strip()}
    )
    quantity = params["args"]["Q3"]
    [value] = re.findall(r"\bvar tax = (\d+\.\d+)\s*;", source)
    fee = float(value)
    assert quantity == 0.5 and fee == 0.0015
    assert (
        "(baseData[1].Buy-baseData[0].Sell*baseData[2].Sell)*Q3>Q3*tax*(2*baseData[1].Buy+baseData[0].Sell*baseData[2].Sell)"
        in source
    )
    assert (
        "baseData[0].Buy*baseData[2].Buy-baseData[1].Sell>(2*baseData[0].Buy*baseData[2].Buy+baseData[1].Sell)*tax"
        in source
    )
    manifest = {
        r["date"]: r
        for r in read(quotes / "manifest.json")
        if r["symbol"] == "BTCUSDT" and r["exchange"] == "binance"
    }
    rows, samples, inputs = [], {}, []
    for date in DATES:
        midnight = int(datetime.fromisoformat(date).replace(tzinfo=UTC).timestamp())
        start, end = midnight + 300, midnight + 28500
        meta = manifest[date]
        windows = [snapshots(quotes / meta["file"], meta, start, end)]
        inputs.append(meta)
        for symbol in ("LTCUSDT", "LTCBTC"):
            filename = f"{date}-{symbol}-quotes.csv.gz"
            path = work / filename
            item = {
                "symbol": symbol,
                "exchange": "binance",
                "date": date,
                "file": filename,
                "sha256": digest(path.read_bytes()),
                "url": f"https://datasets.tardis.dev/v1/binance/quotes/{date.replace('-', '/')}/{symbol}.csv.gz",
            }
            windows.append(snapshots(path, item, start, end))
            inputs.append(item)
        samples[date] = quote_check(windows, start, end, fee, quantity)
        rows.append(
            {
                "id": IDENT,
                "name": strategy["name"],
                "source": url,
                "group": "FMZ · historical triangle quote variant",
                "period": date,
                "market": "BTC/LTC triangle (USDT)",
                "quote_currency": "USDT",
                "interval": "1s sampled quotes",
                "archive_interval": "Top of book",
                "exit": "Archived three-leg quote threshold",
                **metrics([]),
            }
        )
    write(
        output,
        {
            "baseline": "91ad53db",
            "coverage": [
                [IDENT, "Tested · FMZ triangle quote variant, no fills", NOTES]
            ],
            "document_sha256": check["document_sha256"],
            "public_parameters": params,
            "market_data": inputs,
            "original_per_leg_fee": fee,
            "ltc_quantity": quantity,
            "sample_utc": ["00:05", "07:55"],
            "quote_age_limit_ms": 2000,
            "time_alignment_limit_ms": 500,
            "samples": samples,
            "results": rows,
        },
    )
    print(
        sum(s["aligned_samples"] for s in samples.values()),
        "aligned quotes with no source gate passed",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("archive", "quotes", "work", "output"):
        parser.add_argument(field, type=Path)
    run(**vars(parser.parse_args()))
