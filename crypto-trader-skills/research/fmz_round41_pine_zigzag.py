"""Audit weekly zigzag timing and unresolved zero-size opposite stops."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 2954
DAY = 86_400_000
MODES = ("legacy", "v5", "confirmed", "recast")
PROBE = "fmz_round41_pine_zigzag_probe.py"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, checksum),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    settings = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert settings == {
        "start": "2022-10-23 00:00:00",
        "end": "2023-04-14 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert len(re.findall(r"input\((true|false|[0-9]+), defval = \1,", raw)) == 11
    for witness in (
        "//@version=2",
        'needshort = input(false, defval = false, title = "Short")',
        "tf = input('W', title='Timeframe for ZigZag')",
        "useAltTF = true",
        "change(time(tf)) != 0 ? request.security(syminfo.tickerid, tf, zigzag())",
        "dot = zz > 0 ? zz : dot[1]",
        "uplevel = dot > dot[1] ? dot : uplevel[1]",
        "dnlevel = dot < dot[1] ? dot : dnlevel[1]",
        "lot = strategy.position_size != strategy.position_size[1] ? strategy.equity / close * capital / 100 : lot[1]",
        'strategy.entry("Long", strategy.long, needlong == false ? 0 : lot, stop = uplevel + syminfo.mintick)',
        'strategy.entry("Short", strategy.short, needshort == false ? 0 : lot, stop = dnlevel - syminfo.mintick)',
    ):
        assert witness in raw, witness
    link = re.search(r"https://www\.fmz\.com/strategy/\d+", doc)[0]
    return raw.encode(), settings, checksum, link


def market_data(cache):
    start, boundary, history = map(date_ms, ("2022-10-23", "2023-04-14", "2022-09-01"))
    end = 2 * boundary - start
    feed, manifest = {}, []
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(history, end, DAY)
        }
    )
    for symbol in ("BTCUSDT", "ETHUSDT"):
        daily = [
            r
            for r in cache_bars(cache, symbol, "1d", months, DAY, manifest)
            if history <= r[0] < end
        ]
        assert [r[0] for r in daily] == list(range(history, end, DAY))
        for mode, lo, hi in (("native", start, boundary), ("next", boundary, end)):
            weekly = []
            for t, bars in groupby(
                (x for x in daily if x[0] < hi),
                lambda r: ((r[0] // DAY - 4) // 7 * 7 + 4) * DAY,
            ):
                rows = list(bars)
                if rows[0][0] == t:
                    weekly.append(
                        [
                            t,
                            rows[0][1],
                            max(x[2] for x in rows),
                            min(x[3] for x in rows),
                            rows[-1][4],
                            sum(x[5] for x in rows),
                        ]
                    )
            feed.setdefault(mode, {})[symbol] = {
                "chart": [list(r) for r in daily if lo <= r[0] < hi],
                "weekly": weekly,
            }
    return feed, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for key in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--cache", type=Path, nargs="+", required=True)
    a = parser.parse_args()
    raw, settings, checksum, link = source_record(a.archive, a.baseline)
    feeds, manifest = market_data(a.cache)
    source, tape = a.work / "r41-noro-source.pine", a.work / "r41-noro-feeds.json"
    producer = Path(__file__).with_name(PROBE)
    staged = a.work / "r41_noro_probe.py"
    if a.mode == "stage":
        source.write_bytes(raw)
        write(tape, feeds)
        copy2(producer, staged)
        return
    assert source.read_bytes() == raw and read(tape) == feeds
    assert producer.read_bytes() == staged.read_bytes()
    assert (
        sha256(a.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(a.work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    err = a.work / "r41-noro-literal-error.txt"
    errors = [
        line
        for line in err.read_text().splitlines()
        if "E_LEGACY_REFERENCE_TYPE" in line
    ]
    assert len(errors) == 3 and all(
        f"`{name}`" in line
        for name, line in zip(("dot", "uplevel", "dnlevel"), errors, strict=True)
    )
    by_mode, audit, files = {}, [], [source, tape, producer, err]
    for mode in MODES:
        path = a.work / f"r41-noro-{mode}.json"
        files.append(path)
        rows = read(path)
        index = {(r["period"], r["market"]): r for r in rows}
        assert len(rows) == len(index) == 4
        by_mode[mode] = index
    for period, markets in feeds.items():
        for asset, sample in markets.items():
            scope = (period, asset)
            legacy, modern, confirmed, recast = (by_mode[m][scope] for m in MODES)
            assert legacy["strategy"] == modern["strategy"] == confirmed["strategy"]
            assert legacy["plots"] == modern["plots"]
            assert {d["code"] for d in legacy["diagnostics"]} == {
                "W_LEGACY_SECURITY_LOOKAHEAD"
            }
            assert all(not case["diagnostics"] for case in (modern, confirmed, recast))
            assert all(
                not case["strategy"]["diagnostics"]
                for case in (legacy, modern, confirmed, recast)
            )
            assert not confirmed["strategy"]["trades"]
            ((order),) = confirmed["strategy"]["orders"]
            at = order["barIndex"]
            chart = sample["chart"]
            tick = 0.1 if asset == "BTCUSDT" else 0.01
            assert order["id"] == "Long"
            assert order["time"] == chart[at][0]
            assert all(r is None for r in confirmed["plots"]["Lot"][:at])
            assert chart[at][1] <= order["price"] <= chart[at][2]
            assert abs(order["price"] - confirmed["plots"]["Up"][at - 1] - tick) < 1e-8
            alternatives = []
            for timing in (legacy, confirmed):
                down = timing["plots"]["Down"]
                reaches = [
                    chart[i][0]
                    for i in range(at + 1, len(chart))
                    if down[i - 1] and chart[i][3] <= down[i - 1] - tick
                ]
                alternatives.append(reaches)
            assert len(recast["strategy"]["trades"]) == 1
            close = recast["strategy"]["trades"][0]
            assert close["exitTime"] == alternatives[1][0]
            audit.append(
                {
                    "period": period,
                    "market": asset,
                    "literal_order_path_comparison": order,
                    "legacy_touched_stop_bars": alternatives[0],
                    "confirmed_touched_stop_bars": alternatives[1],
                    "rewritten_reduce_only_first_exit": close,
                    "executed_source_sha256": {
                        m: by_mode[m][scope]["executed_source_sha256"] for m in MODES
                    },
                }
            )
    x = next(r for r in audit if r["period"] == "native" and r["market"] == "ETHUSDT")
    assert (
        not x["legacy_touched_stop_bars"] and len(x["confirmed_touched_stop_bars"]) == 4
    )
    write(
        a.output,
        {
            "baseline_coverage_sha256": sha256(a.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": checksum,
            "archived_settings": settings,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "provider_archives": manifest,
            "artifacts": {f.name: sha256(f) for f in files},
            "literal_diagnostics": errors,
            "diagnostic_only_scopes": audit,
            "references": [
                link,
                "https://www.tradingview.com/script/6VfA6sTZ-noro-s-zz-strategy-v1-0/",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
                "https://www.fmz.com/doc/9293#strategyentry",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "Keep the archived equal duplicate inputs at their authored values. Specify recursive scalar types using the original missing-value startup. The legacy control uses the older security/ticker names and the same explicitly supplied symbol tick. The modern lookahead-on control matches all legacy values.",
                "A previous-confirmed-week variant changes active pivot and stop levels. The exact saved and equal later daily BTC/ETH tapes verify opening stop price eligibility. The initial recursive quantity is missing until a position changes. All three timing variants ignore the authored zero-size opposite stops in Pine Compat and leave four holdings.",
                "The resulting non-repainting stop levels are reachable on BTC/ETH. The archived-window ETH has four touches when using only available weeks versus zero in the future-aware diagnostic. Replacing short entries by a reduce-only exit changes order semantics and closes four positions. This comparison makes native FMZ order interpretation material. The original market tape is public but its zero-quantity and confirmed-timing behavior remains unverified.",
            ],
            "coverage": [
                [
                    IDENT,
                    "Pending · FMZ weekly pivot timing and zero-quantity stop semantics",
                    "Recovered eleven equal duplicate defaults, typed recursion and legacy security spelling. Literal-candidate and confirmed controls open the same four holdings and ignore the archived qty=0 stops in Pine Compat. Causal weekly handling changes stop touches from zero to four in saved-window ETH. A rewritten reduce-only variant closes all four positions, so the host's missing broker semantics change realized results.",
                ]
            ],
            "results": [],
        },
    )
    print("Verified 16 diagnostic scopes and exact pending disposition for #2954.")


if __name__ == "__main__":
    main()
