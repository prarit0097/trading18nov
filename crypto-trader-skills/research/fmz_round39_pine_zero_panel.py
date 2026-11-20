"""Audit zero-size opposite limits and stops across the saved Pine engines."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from datetime import UTC, datetime
from hashlib import sha512
from pathlib import Path
from shutil import copy2
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import PINER_PIN
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 4650
DAY = 86_400_000
HOUR = 3_600_000
MODES = ("literal", "v5", "magnified", "bracket")
PY = "fmz_round39_pine_zero_panel_probe.py"
JS = "fmz_round39_pine_zero_panel.mjs"


def acquire(archive, baseline, daily, hourly):
    assert sha256(archive) == FMZ_SHA256
    (r,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert r["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, datum, doc, digest),) = documents(book, {IDENT: r})
    (script,) = re.findall(
        r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc
    )
    published = re.search(r"https://www\.fmz\.com/strategy/\d+", doc)[0]
    settings = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", script
        )
    )
    assert settings == {
        "start": "2023-01-01 00:00:00",
        "end": "2023-11-09 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    order_code, sep, display = script.partition("//Lines")
    assert sep and "strategy.entry" in order_code and "strategy" not in display
    for witness in (
        "ma = sma(ohlc4, 3)",
        "lo = input(-5.0",
        "tp = input(5.0",
        "sl = input(2.0",
        'strategy.entry("Long", strategy.long, limit = long)',
        'strategy.entry("Take", strategy.short, 0, limit = avg + ((avg / 100) * tp))',
        'strategy.entry("Stop", strategy.short, 0, stop = avg - ((avg / 100) * sl))',
        "if strategy.position_size == 0",
        'strategy.cancel("Take")',
        'strategy.cancel("Stop")',
    ):
        assert witness in order_code, witness
    start, cut = map(date_ms, (settings["start"], settings["end"]))
    end = 2 * cut - start
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(start, end, DAY)
        }
    )
    feeds, market_hashes = {}, []
    for market in ("BTCUSDT", "ETHUSDT"):
        d = [
            r
            for r in cache_bars(daily, market, "1d", months, DAY, market_hashes)
            if start <= r[0] < end
        ]
        h = [
            r
            for r in cache_bars(hourly, market, "1h", months, HOUR, market_hashes)
            if start <= r[0] < end
        ]
        assert [r[0] for r in d] == list(range(start, end, DAY))
        assert [r[0] for r in h] == list(range(start, end, HOUR))
        assert all(x[:5] == y[:5] for x, y in zip(d, aggregate(h, 24), strict=True))
        for period, a, b in (("native", start, cut), ("next", cut, end)):
            feeds.setdefault(period, {})[market] = {
                "chart": [list(r) for r in d if a <= r[0] < b],
                "base": [list(r) for r in h if a <= r[0] < b],
                "ambiguous": [],
            }
    return datum, digest, settings, published, script.encode(), feeds, market_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "python_work", "node_work", "output"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    for name in ("daily", "hourly"):
        parser.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    a = parser.parse_args()
    _, digest, settings, published, raw, data, source_files = acquire(
        a.archive, a.baseline, a.daily, a.hourly
    )
    py, js = Path(__file__).with_name(PY), Path(__file__).with_name(JS)
    p, n = a.python_work, a.node_work
    paths = [(p, py, "r39_panel_probe.py"), (n, js, "r39_panel_piner.mjs")]
    if a.mode == "stage":
        for work, runner, name in paths:
            copy2(runner, work / name)
            (work / "r39-panel-source.pine").write_bytes(raw)
            write(work / "r39-panel-feeds.json", data)
        return
    for work, runner, name in paths:
        assert runner.read_bytes() == (work / name).read_bytes()
        assert (work / "r39-panel-source.pine").read_bytes() == raw
        assert read(work / "r39-panel-feeds.json") == data
    assert (
        sha256(p / "priced-runtime/pine_compat/pine_compat.pyd") == NATIVE_BINARY_HASH
    )
    py_isolation = read(p / "round3-isolation-python.json")
    assert all(
        py_isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    js_isolation = read(n / "isolation-probe.json")
    assert js_isolation == {"privateDenied": True, "networkDenied": True}
    pkg = n / "piner-0.13.0.tgz"
    assert b64encode(sha512(pkg.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(pkg, "r:gz") as package:
        assert (
            package.extractfile("package/dist/index.js").read()
            == (n / "package/dist/index.js").read_bytes()
        )
    node = n / "r39-panel-piner.json"
    orders = read(node)
    assert len(orders) == 8
    piner = {(r["period"], r["market"], r["backend"]): r for r in orders}
    paths = {mode: p / f"r39-panel-{mode}.json" for mode in MODES}
    variants = {}
    for mode, path in paths.items():
        native = read(path)
        assert len(native) == 4
        variants[mode] = {(r["period"], r["market"]): r for r in native}
        assert all(
            not r["diagnostics"] and not r["strategy"]["diagnostics"] for r in native
        )
    summary = []
    counterexample = None
    for period, markets in data.items():
        for market, tape in markets.items():
            key = (period, market)
            literal = variants["literal"][key]["strategy"]
            limit = variants["bracket"][key]["strategy"]
            compatible = piner[(*key, "js")]
            independent = piner[(*key, "interp")]
            assert all(
                compatible[k] == independent[k] for k in ("closed", "pos", "unsettled")
            )
            assert len(literal["orders"]) == 1 and not literal["trades"]
            assert literal["position"][-1]["size"] > 0
            assert all(
                literal == variants[m][key]["strategy"] for m in ("v5", "magnified")
            )
            assert len(limit["trades"]) > 0
            assert limit["orders"][0] == literal["orders"][0]
            if key == ("native", "BTCUSDT"):
                lot = compatible["closed"][0]
                native_order = literal["orders"][0]
                i = lot["entryBar"]
                day = tape["chart"][i]
                hours = tape["base"][24 * i : 24 * (i + 1)]
                assert lot["entryTime"] == lot["exitTime"] == day[0]
                assert native_order["barIndex"] == i and equal(
                    native_order["price"], lot["entryPrice"]
                )
                assert lot["exitPrice"] == day[1]
                first = next(
                    j for j, hour in enumerate(hours) if hour[3] <= lot["entryPrice"]
                )
                subsequent_high = max(h[2] for h in hours[first:])
                assert first == 20 and subsequent_high < lot["exitPrice"]
                counterexample = {
                    "market": market,
                    "chart_bar_open": day[0],
                    "entry_limit": lot["entryPrice"],
                    "earliest_eligible_1h_start": hours[first][0],
                    "later_same_day_high_including_first_eligible_hour": subsequent_high,
                    "piner_claimed_same_day_exit": lot["exitPrice"],
                    "distinct_counterfactual_exit_bar": limit["trades"][0]["exitTime"],
                }
            summary.append(
                {
                    "period": period,
                    "market": market,
                    "literal_closes": len(literal["trades"]),
                    "literal_terminal_quantity": literal["position"][-1]["size"],
                    "piner_closes": len(compatible["closed"]),
                    "rewrite_only_closes": len(limit["trades"]),
                }
            )
    assert counterexample is not None
    assert sum(row["piner_closes"] for row in summary) == 147
    assert sum(row["rewrite_only_closes"] for row in summary) == 95
    write(
        a.output,
        {
            "baseline_coverage_sha256": sha256(a.baseline),
            "archive_sha256": FMZ_SHA256,
            "pinned_source_sha256": digest,
            "archived_config": settings,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "piner_tarball_sha512": PINER_PIN,
            "isolation": {"python": py_isolation, "node": js_isolation},
            "provider_archives": source_files,
            "artifacts": {f.name: sha256(f) for f in (py, js, node, *paths.values())},
            "per_scope_diagnostic_counts": summary,
            "impossible_piner_fill_witness": counterexample,
            "method": [
                "Literal Pine v4, a syntax-only v5 port, and magnified verified 1h data produce no exits in Pine Compat. The engine does not execute the 0-quantity opposite orders. A pinned timestamp only supplies the display clock within the original Pine code.",
                "Piner JS and interpreter agree on the number of fills but fail exact chronology. On the first saved BTC fill the exit price equals the daily open. The market enters the buy limit range only in a later hour and never returns to the claimed exit price that day.",
                "An explicit reduce-only strategy.exit bracket is an independent comparator that changes the source order lifecycle. It has 95 closes and supplies no verified results rows. The actual FMZ archived host behavior for opposite 0-quantity priced entry orders still has no exact fixture.",
            ],
            "references": [
                published,
                "https://www.fmz.com/doc/9293#strategyentry",
                "https://www.tradingview.com/pine-script-docs/v4/essential/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    "Pending · FMZ opposite zero-quantity priced entry semantics",
                    "Three Pine Compat modes ignore the archived qty=0 opposite priced orders and yield zero exits, while both Piner backends yield 147 closes including a demonstrably impossible BTC same-day exit on exact hourly data. A rewritten bracket changes orders and yields 95 closes. Exact original host behavior is missing.",
                ]
            ],
            "results": [],
        },
    )
    print(
        "Verified 24 engine scope receipts and one causal impossibility witness. Strategy remains pending."
    )


if __name__ == "__main__":
    main()
