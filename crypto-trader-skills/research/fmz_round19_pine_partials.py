"""Replay the restored FMZ EMA strategy with two partial reductions and a stop."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from collections import defaultdict
from hashlib import sha512
from itertools import chain
from math import floor, fsum, isclose
from pathlib import Path
from shutil import copy2, copytree
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256, verified_archives
from research.fmz_round7_pine import (
    EXECUTION,
    FEE,
    PINER_PIN,
    PINER_VERSION,
    strip_fmz_wrapper,
    summarize,
    verify_trade,
)
from research.fmz_round11_pine_playzone import exponential
from research.fmz_round12_pine_authored import aligned, provider_bars
from research.fmz_round18_pine_qqe import executable_lines

ID = 5457
CAPITAL, CASH = 10_000, 1_000
LOT_STEP = 0.001
HOUR = 3_600_000
MARKETS = ("BTCUSDT", "ETHUSDT")
GROUP = "FMZ Pine · Native 1h · Verified partial exits and protective stop"


def trim_variant(code):
    for name, value in (
        ("anchor", "4"),
        ("len1", "16"),
        ("len2", "21"),
        ("len3", "26"),
        ("type1", '"EMA"'),
        ("type2", '"EMA"'),
        ("type3", '"EMA"'),
        ("RSIsrc", "close"),
    ):
        assert re.search(
            rf"(?m)^{name}\s*=\s*input\((?:defval=)?{re.escape(value)},", code
        ), name
    assert (
        "trade_dir = input('Long Only'," in code
        and "strategy.risk.allow_entry_in(dir)" in code
    )
    for var, value in (("tp1_perc", "25"), ("tp2_perc", "25"), ("sl_perc", "2")):
        assert re.search(rf"(?m)^{var}\s*=\s*input\({value},[^\n]+\)/100$", code), var
    assert "window = true  //" in code
    assert (
        "tcolor = direction<0?red:green" in code
        and "altTcolor=altDirection<0?red:green" in code
    )
    assert "direction = rising(ma_medium,3) ? 1 : falling(ma_medium,3) ? -1 : 0" in code
    assert (
        "altDirection = rising(ma_medium_alt,3) ? 1 : falling(ma_medium_alt,3) ? -1 : 0"
        in code
    )
    assert "turned_aqua = altTcolor[1] == red and altTcolor == green" in code
    assert "turned_blue = altTcolor[1] == green and altTcolor == red" in code
    decl = re.search(
        r'(?ms)^strategy\(\s*title="\[Alerts\]QQE Cross v6.0 by JustUncleL",\s*shorttitle="\[AL\]QQEX v6.0",\s*overlay=true\)',
        code,
    )[0]
    setup = [
        "//@version=5",
        " ".join(line.strip() for line in decl.splitlines() if line.strip()),
        "strategy.risk.allow_entry_in(strategy.direction.long)",
        "window = true",
        "tp1_perc=0.25",
        "tp2_perc=0.25",
        "sl_perc=0.02",
        "ma_medium=ta.ema(close,21)",
        "ma_slow=ta.ema(close,26)",
        "ma_fast_alt=ta.ema(close,64)",
        "ma_medium_alt=ta.ema(close,84)",
        "ma_slow_alt=ta.ema(close,104)",
        "medDown = bar_index>=3 and ma_medium<math.min(ma_medium[1],ma_medium[2],ma_medium[3])",
        "altDown = bar_index>=3 and ma_medium_alt<math.min(ma_medium_alt[1],ma_medium_alt[2],ma_medium_alt[3])",
        "turned_aqua = altDown[1] and not altDown",
        "turned_blue = not altDown[1] and altDown",
    ]
    for mode, old, new in (
        ("long", "tcolor[1] == green and tcolor == red", "not medDown[1] and medDown"),
        ("short", "tcolor[1] == red and tcolor == green", "medDown[1] and not medDown"),
    ):
        (line,) = re.findall(rf"(?m)^take_profit_{mode} = [^\n]*", code)
        assert old in line
        setup.append(line.replace(old, new))
    body = re.search(
        r'(?ms)^strategy.entry\("Long", strategy.long, when=turned_aqua and window\).*?^strategy.exit\("S-SL", "Short", stop=short_sl_level\)',
        code,
    )[0]
    body = re.sub(
        r"(?m)^(long_tp[12]_qty|short_tp[12]_qty) = na$", r"var float \1 = na", body
    )
    setup.extend(
        line
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    )
    setup.extend(
        (
            'plot(ma_medium,"Medium")',
            'plot(ma_slow,"Slow")',
            'plot(ma_medium_alt,"Alt medium")',
            'plot(ma_fast_alt,"Alt fast")',
            'plot(ma_slow_alt,"Alt slow")',
            'plot(turned_aqua?1:0,"Enter")',
            'plot(turned_blue?1:0,"Opposite")',
            'plot(take_profit_long?1:0,"Partial")',
            'plot(strategy.position_size,"Position")',
            'plot(strategy.position_avg_price,"Average")',
            'plot(long_tp_count,"Count")',
            'plot(long_tp1_qty,"Partial qty")',
            "",
        )
    )
    return "\n".join(setup)


def expected_filters(chart):
    prices = [row[4] for row in chart]
    medium, slow, alt, fast_alt, slow_alt = (
        exponential(prices, n) for n in (21, 26, 84, 64, 104)
    )
    med_red = alt_red = False
    enter = []
    opposite = []
    partial = []
    for i in range(len(chart)):
        next_med = i >= 3 and medium[i] < min(medium[i - 3 : i])
        next_alt = i >= 3 and alt[i] < min(alt[i - 3 : i])
        enter.append(int(alt_red and not next_alt))
        opposite.append(int(not alt_red and next_alt))
        partial.append(
            int(
                not med_red
                and next_med
                and slow[i] > fast_alt[i]
                and slow[i] > slow_alt[i]
            )
        )
        med_red = next_med
        alt_red = next_alt
    return medium, slow, alt, fast_alt, slow_alt, enter, opposite, partial


def independent_broker(chart, signals):
    enter, opposite, partial = signals[-3:]
    entry = None
    qty = 0.0
    trim = None
    counter = None
    mark, average, counts, trim_sizes = [], [], [], []
    fills = []
    partial_events = stops = round_trips = 0
    for i, bar in enumerate(chart):
        o = bar[1]
        lo = bar[3]
        previous_qty = qty
        if i:
            past_stop = chart[entry][1] * 0.98 if qty else None
            next_entry = enter[i - 1]
            close_at_open = opposite[i - 1]
            pending_trim = bool(
                qty
                and i >= 2
                and partial[i - 1]
                and counts[i - 2] in (0, 1)
                and not close_at_open
            )
            assert not (pending_trim and past_stop is not None and o <= past_stop), (
                "simultaneous partial and stop gap",
                i,
            )
            if next_entry and not qty:
                qty = floor(CASH / o / LOT_STEP) * LOT_STEP
                entry = i
            if close_at_open and qty:
                fills.append((entry, i, qty, o))
                round_trips += 1
                qty = 0
                entry = None
            if pending_trim:
                assert qty and trim > 0 and trim < qty
                fills.append((entry, i, trim, o))
                qty -= trim
                partial_events += 1
            if qty and past_stop is not None and lo <= past_stop:
                fills.append((entry, i, qty, min(o, past_stop)))
                qty = 0
                entry = None
                stops += 1
                round_trips += 1
        if qty and not previous_qty:
            counter = 0
            trim = qty * 0.25
        elif partial[i] and counter is not None:
            counter += 1
        mark.append(qty)
        average.append(chart[entry][1] if qty else None)
        counts.append(counter)
        trim_sizes.append(trim)
    return (
        (mark, average, counts, trim_sizes),
        fills,
        qty,
        (partial_events, stops, round_trips),
    )


def verify(case, payload):
    chart = payload["chart"]
    expected = expected_filters(chart)
    state, fills, remaining, types = independent_broker(chart, expected)
    assert not case["requested"]
    for wn, (calculated, actual) in enumerate(
        zip((*expected, *state), case["witnesses"], strict=True)
    ):
        for i, (x, y) in enumerate(zip(calculated, actual, strict=True)):
            assert (x is None and y is None) or (
                x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-10, abs_tol=1e-8)
            ), (wn, i, x, y)
    assert case["unsettled"] == int(bool(remaining))
    assert len(case["closed"]) == len(fills)
    events = []
    times = [row[0] for row in chart]
    grouped = defaultdict(list)
    for trade, (i, j, qty, out) in zip(case["closed"], fills, strict=True):
        assert (
            trade["entryBar"],
            trade["exitBar"],
            trade["dir"],
            trade["entryId"],
        ) == (i, j, 1, "Long")
        assert chart[i][5] > 0 and chart[j][5] > 0
        assert isclose(trade["entryPrice"], chart[i][1], rel_tol=1e-11, abs_tol=1e-8)
        assert isclose(trade["exitPrice"], out, rel_tol=1e-11, abs_tol=1e-8)
        assert isclose(trade["qty"], qty, rel_tol=1e-11, abs_tol=1e-11)
        record = verify_trade(trade, times)
        grouped[i].append(record)
        events.append(record)
    return events, grouped, types


START = "2023-10-06"
END = "2023-11-05"
WINDOWS = (
    ("FMZ native window", date_ms(START), date_ms(END)),
    ("Next equal window", date_ms(END), 2 * date_ms(END) - date_ms(START)),
)


def archived_source(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [entry for entry in read(baseline)["disposition"] if entry["id"] == ID]
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as source:
        ((_, _, document, digest),) = documents(source, {ID: row})
    (fenced,) = re.findall(
        r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
    )
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", fenced
        )
    )
    assert fields == {
        "start": f"{START} 00:00:00",
        "end": f"{END} 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    source_text, wrapped = strip_fmz_wrapper(fenced.replace("\r\n", "\n"))
    assert wrapped
    original = executable_lines(source_text)
    assert not any("/*" in line for line in original)
    legacy = executable_lines(re.sub(r"/\*.*?\*/", "", fenced, flags=re.DOTALL))
    restored = original - legacy
    assert sum(restored.values()) == 47
    calls = re.findall(r"\bstrategy\.(entry|exit|order|close)\(", "\n".join(original))
    assert calls == [
        "entry",
        "entry",
        "order",
        "order",
        "order",
        "order",
        "exit",
        "exit",
    ]
    return row, digest, fields, source_text.encode(), trim_variant(source_text).encode()


def provider_cases(public):
    manifest, feeds = [], {}
    for market in MARKETS:
        archives = verified_archives(
            public, market, "1h", ("2023-10", "2023-11", "2023-12"), manifest
        )
        bars = list(chain.from_iterable(provider_bars(path, HOUR) for path in archives))
        for label, start, end in WINDOWS:
            chart = aligned(bars, start, end, 60, 60)
            assert chart[0][0] == start and chart[-1][0] + HOUR == end
            feeds.setdefault(label, {})[market] = {"chart": chart, "frame": "60"}
    return manifest, {str(ID): feeds}


def stage(archive, baseline, public, runtime, work):
    _, _, _, source, executed = archived_source(archive, baseline)
    _, feeds = provider_cases(public)
    work.mkdir(parents=True, exist_ok=True)
    if runtime.resolve() != work.resolve():
        for name in (
            "node.exe",
            f"piner-{PINER_VERSION}.tgz",
            "probe.cjs",
            "sandbox.ps1",
        ):
            copy2(runtime / name, work / name)
        copytree(runtime / "package", work / "package", dirs_exist_ok=True)
    copy2(Path(__file__).with_suffix(".mjs"), work / "trim-run.mjs")
    (work / f"source-{ID}.pine").write_bytes(source)
    (work / f"variant-{ID}.pine").write_bytes(executed)
    write(work / "trim-feeds.json", feeds)


def check_runtime(work):
    assert (work / "trim-run.exit").read_text().strip() == "0"
    assert (work / "trim-run.mjs").read_bytes() == Path(__file__).with_suffix(
        ".mjs"
    ).read_bytes()
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as dist:
        assert (
            dist.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    return isolation


def round_trips(grouped):
    events = []
    for legs in grouped.values():
        columns = list(zip(*legs, strict=True))
        events.append((max(columns[0]), *(fsum(col) for col in columns[1:])))
    return events


def metrics_by_position(positions, legs, open_count, capital):
    totals = summarize(positions, open_count, capital)
    leg_metrics = summarize(legs, open_count, capital)
    for key, value in leg_metrics.items():
        if "_dd" in key:
            totals[key] = value
    assert isclose(totals["net"], leg_metrics["net"], rel_tol=1e-10, abs_tol=1e-8)
    return totals


def finalize(archive, baseline, public, work, output):
    row, digest, settings, source, variant = archived_source(archive, baseline)
    manifest, feeds = provider_cases(public)
    assert read(work / "trim-feeds.json") == feeds
    isolation = check_runtime(work)
    (receipt,) = read(work / "trim-receipt.json")
    assert receipt["id"] == ID and len(receipt["cases"]) == 4
    raw, executed = work / f"source-{ID}.pine", work / f"variant-{ID}.pine"
    assert raw.read_bytes() == source and executed.read_bytes() == variant
    assert receipt["sourceHash"] == sha256(raw) and receipt["variantHash"] == sha256(
        executed
    )
    cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
    assert len(cases) == 4
    common = {
        "id": ID,
        "name": row["name"],
        "source": row["source"],
        "source_sha256": digest,
        "executed_source_sha256": receipt["variantHash"],
        "interval": "1h",
        "archive_interval": "1h",
        "quote_currency": "USDT",
        "group": GROUP,
        "market_data": "Binance USD-M native historical 1h candles",
        "exit": "Two market partials, 2% protective stop, or opposite signal close",
    }
    rows, event_counts = [], []
    for label, markets in feeds[str(ID)].items():
        legs_pool, positions_pool, open_count = [], [], 0
        for market, payload in markets.items():
            case = cases[(label, market)]
            legs, grouped, (partials, stops, fully_closed) = verify(case, payload)
            positions = round_trips(grouped)
            assert (
                len(positions) == fully_closed and len(legs) == fully_closed + partials
            )
            remaining = case["unsettled"]
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": market,
                    **metrics_by_position(positions, legs, remaining, CAPITAL),
                }
            )
            event_counts.append(
                {
                    "period": label,
                    "market": market,
                    "fully_closed": fully_closed,
                    "realized_exit_legs": len(legs),
                    "partial_reductions": partials,
                    "protective_stops": stops,
                }
            )
            legs_pool.extend(legs)
            positions_pool.extend(positions)
            open_count += remaining
        rows.append(
            {
                **common,
                "period": label,
                "market": "BTCUSDT + ETHUSDT",
                **metrics_by_position(
                    positions_pool, legs_pool, open_count, 2 * CAPITAL
                ),
            }
        )
    closed = sum(counts["fully_closed"] for counts in event_counts)
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": manifest,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in ("trim-feeds.json", "trim-run.mjs", "trim-receipt.json")
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "entry_lot_step": LOT_STEP,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "Direct extraction of the pinned Pine fence restores 47 active lines removed by a broken comment regex. The two 25% source reductions, 2% protective stop, long-only permission, active EMA defaults and both original order-path directions are preserved.",
                "The authored trade signals read five EMA lengths and two three-bar falling tests. They use color transitions, with falling interpreted as the current EMA being below all previous three observations. The QQE block is outside the active order dependency.",
                "The independent broker checks next-open entries and partials, group-specific quantities, the single live protective stop, positive-volume price bars and cases with potential same-open partial/stop interactions. No tested case contains a partial competing with a gapped stop at the same open.",
                "Win rates and closed-trade counts use completed positions. P&L includes each realized leg and drawdown is computed on the realized leg sequence. Open positions contain no realized terminal partials in these samples.",
                "The partial quantities and stop prices reproduce the authored historical Pine simulation, with no venue-lot or tick rounding added to explicit fractional exits. BTC matches the archived Binance venue, ETH is a same-venue comparison, and the following chronological window resets process state.",
            ],
            "source_audits": {
                ID: {
                    "archive_settings": settings,
                    "source_document_sha256": digest,
                    "closed": closed,
                }
            },
            "per_case_order_counts": event_counts,
            "coverage": [
                [
                    ID,
                    f"Tested · {GROUP}",
                    "Restored archived defaults and independently verified two partial reductions, market reversals, protective stops, and net cashflows.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"Verified {len(rows)} rows, {closed} completed positions and {sum(item['realized_exit_legs'] for item in event_counts)} realized legs."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, arguments in (
        ("stage", stage, ("archive", "baseline", "public", "runtime", "work")),
        ("finalize", finalize, ("archive", "baseline", "public", "work", "output")),
    ):
        operation = commands.add_parser(name)
        for argument in arguments:
            operation.add_argument(argument, type=Path)
        operation.set_defaults(handler=handler)
    settings = vars(parser.parse_args())
    settings.pop("command")
    settings.pop("handler")(**settings)


if __name__ == "__main__":
    main()
