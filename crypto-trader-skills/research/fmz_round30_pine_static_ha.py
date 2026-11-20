"""Verify a legacy nested security merge and the authored default filters."""

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
from research.fmz_round7_magnifier import (
    FMZ_SHA256,
    aggregate,
    date_ms,
    sha256,
    verified_archives,
)
from research.fmz_round7_pine import (
    FEE,
    PINER_PIN,
    PINER_VERSION,
    summarize,
    verify_trade,
)
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH

IDENT = 939
DAY = 86_400_000
FOUR_HOURS = 14_400_000
CAPITAL = 1_000_000
GROUP = "FMZ Pine · Static nested daily inputs · Source-default reversal"
MARKETS = ("BTCUSDT", "ETHUSDT")
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
NATIVE = "fmz_round30_pine_static_requests.py"
PINE = """//@version=5
strategy("Smooth HA Candles MTF v1", overlay=true)
srcOpen=request.security("CONTEXT:OPEN", timeframe.period, close)
srcClose=request.security("CONTEXT:CLOSE", timeframe.period, close)
sampledEma(feed,len) =>
    a = 2.0/(len+1)
    state=0.0
    state := na(feed) ? state[1] : na(state[1]) ? feed : a*feed+(1-a)*state[1]
dema(src, len) =>
    ma1 = sampledEma(src, len)
    ma2 = sampledEma(ma1, len)
    2 * ma1 - ma2
tema(src, len) =>
    ma1 = sampledEma(src, len)
    ma2 = sampledEma(ma1, len)
    ma3 = sampledEma(ma2, len)
    3 * (ma1 - ma2) + ma3
tdema(src, len) =>
    ma1 = dema(src, len)
    ma2 = dema(ma1, len)
    ma3 = dema(ma2, len)
    3 * (ma1 - ma2) + ma3
ttema(src, len) =>
    ma1 = tema(src, len)
    ma2 = tema(ma1, len)
    ma3 = tema(ma2, len)
    3 * (ma1 - ma2) + ma3
o1=math.avg(ttema(srcOpen,25),tdema(srcOpen,25))
c1=math.avg(ttema(srcClose,25),tdema(srcClose,25))
buySignal=ta.crossover(c1,o1) and c1>o1
sellSignal=ta.crossunder(c1,o1) and c1<o1
if buySignal
    strategy.entry("buy", strategy.long)
else if sellSignal
    strategy.entry("sell", strategy.short)
plot(srcOpen,"Open")
plot(srcClose,"Close")
plot(o1,"Smoothed open")
plot(c1,"Smoothed close")
plot(buySignal?1:0,"Long")
plot(sellSignal?1:0,"Short")
plot(strategy.position_size,"Position")
"""


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as z:
        ((_, item, document, digest),) = documents(z, {IDENT: row})
    (raw,) = re.findall(
        r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
    )
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2021-05-08 00:00:00",
        "end": "2022-05-07 23:59:00",
        "period": "4h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    active = "\n".join(executable_lines(raw))
    assert "//@version=4" in raw
    for token in (
        'study("Smooth HA Candles MTF v1",overlay=true)',
        'higherTf = input("D", "TF", type = input.resolution)',
        'type = input(defval="AVG",',
        "len = input(25,",
        "showma = input(true,",
        "avg(ttema(src, len), tdema(src, len))",
        "2 * ma1 - ma2",
        "3 * (ma1 - ma2) + ma3",
        'strategy.entry("buy", strategy.long)',
        'strategy.entry("sell", strategy.short)',
    ):
        assert token in active, token
    for i, name in enumerate(("c", "o", "l", "h")):
        k = "" if i == 0 else str(i)
        a = f"ec1ft{k} = security(syminfo.tickerid, higherTf, data{k}[1], gaps = barmerge.gaps_off,"
        assert a in active
        assert (
            f"{name} = security(heikinashi(syminfo.tickerid), higherTf, ec1ft{k})"
            in active
        )
    assert active.count("lookahead = barmerge.lookahead_on") == 4
    assert len(re.findall(r"\bstrategy\.(entry|close|exit|order)\(", active)) == 2
    return item, digest, fields, raw.encode()


def inputs(public):
    start, stop, prefix = map(date_ms, ("2021-05-08", "2022-05-08", "2021-05-01"))
    end = 2 * stop - start
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(prefix, end, DAY)
        }
    )
    manifest = []
    data = {}
    for market in MARKETS:
        source = [
            r
            for arc in verified_archives(public, market, "4h", months, manifest)
            for r in provider_bars(arc, FOUR_HOURS)
            if prefix <= r[0] < end
        ]
        assert [r[0] for r in source] == list(range(prefix, end, FOUR_HOURS))
        daily = list(aggregate(source, 6))
        for period, lo, hi in (("native", start, stop), ("next", stop, end)):
            candles = [list(r) for r in source if lo <= r[0] < hi]
            full = [list(r) for r in daily if r[0] < hi]
            data.setdefault(period, {})[market] = {"chart": candles, "daily": full}
    return manifest, data


def project(payload):
    chart = payload["chart"]
    daily = {bar[0]: bar for bar in payload["daily"]}
    outputs = {"chart": chart, "open": [], "close": []}
    for bar in chart[5:]:
        time = bar[0]
        day, offset = divmod(time, DAY)
        days_before = 1 if offset == 5 * FOUR_HOURS else 2
        ref = daily[(day - days_before) * DAY]
        for name, index in (("open", 1), ("close", 4)):
            value = ref[index]
            outputs[name].append([time, value, value, value, value, 0])
    return outputs


def projections(data):
    return {
        period: {m: project(tape) for m, tape in cases.items()}
        for period, cases in data.items()
    }


def stage(archive, baseline, work, native, public):
    _, _, _, raw = source_record(archive, baseline)
    _, data = inputs(public)
    (native / "round28-ha-source.pine").write_bytes(raw)
    write(native / "round28-ha-feeds.json", data)
    copy2(Path(__file__).with_name(NATIVE), native / "r28_ha_requests.py")
    (work / "round29-ha-variant.pine").write_bytes(PINE.encode())
    write(work / "round29-ha-js-feeds.json", projections(data))
    copy2(Path(__file__).with_suffix(".mjs"), work / "round29-ha-run.mjs")


def ema(values):
    prior = None
    for v in values:
        prior = (
            (v if prior is None else 2.0 / 26 * v + (1 - 2.0 / 26) * prior)
            if v is not None
            else prior
        )
        yield prior


def dema(seq):
    a = list(ema(seq))
    b = list(ema(a))
    return [None if x is None else 2 * x - y for x, y in zip(a, b, strict=True)]


def triple(seq2, fn):
    a = fn(seq2)
    b = fn(a)
    c = fn(b)
    return [
        None if x is None else 3 * (x - y) + z for x, y, z in zip(a, b, c, strict=True)
    ]


def tema(values):
    a = list(ema(values))
    b = list(ema(a))
    c = list(ema(b))
    return [
        None if x is None else 3 * (x - y) + z for x, y, z in zip(a, b, c, strict=True)
    ]


def avg(v):
    return [
        None if x is None else (x + y) / 2
        for x, y in zip(triple(v, tema), triple(v, dema), strict=True)
    ]


def traces(legacy, feed, projection):
    daily = {c[0]: c for c in feed["daily"]}
    candles = feed["chart"]
    old = legacy["result"]
    assert old["mode"] == "derived"
    for field, inner, outer, index in (
        ("open", "ec1ft1", "o", 1),
        ("close", "ec1ft", "c", 4),
    ):
        first = [daily[(bar[0] // DAY - 1) * DAY][index] for bar in candles]
        second = [None] * 5 + [row[4] for row in projection[field]]
        assert first == old["plots"][inner] and second == old["plots"][outer]
    return len(candles) * 4


def orders(case, payload):
    chart = payload["chart"]
    opened = [None] * 5 + [v[4] for v in payload["open"]]
    closed = [None] * 5 + [v[4] for v in payload["close"]]
    smooth_o, smooth_c = avg(opened), avg(closed)
    lag = None
    signals = []
    for a, b in zip(smooth_o, smooth_c, strict=True):
        diff = None if a is None else b - a
        signals.append(
            (
                diff is not None and lag is not None and diff > 0 and lag <= 0,
                diff is not None and lag is not None and diff < 0 and lag >= 0,
            )
        )
        lag = diff
    long, short = zip(*signals, strict=True)
    observed = case["witnesses"]
    for series, (oracle, seen) in enumerate(
        zip(
            (opened, closed, smooth_o, smooth_c, long, short),
            observed[:-1],
            strict=True,
        )
    ):
        for i, (a, b) in enumerate(zip(oracle, seen, strict=True)):
            assert equal(a, b), (series, i, a, b)

    desired, direction = 0, 0
    held = None
    expected, state = [], []
    for index, (row, (buy, sell)) in enumerate(zip(chart, signals, strict=True)):
        if desired and desired != direction:
            if held is not None:
                expected.append((direction, held, chart[held][1], index, row[1]))
            held, direction = index, desired
        state.append(direction)
        assert not (buy and sell)
        desired = 1 if buy else -1 if sell else 0
    assert state == observed[-1]
    assert case["open"] == int(bool(direction))
    times = [r[0] for r in chart]
    ledger = []
    for prior, r in zip(expected, case["trades"], strict=True):
        assert r["qty"] == 1
        fields = ("dir", "entryBar", "entryPrice", "exitBar", "exitPrice")
        assert prior == tuple(r[k] for k in fields)
        ledger.append(verify_trade(r, times))
    return (
        ledger,
        case["open"],
        {
            "closed": len(ledger),
            "comparison_values": len(state) * len(observed),
            "terminal_position": state[-1],
        },
    )


def report(archive, baseline, work, native, public, output):
    old, digest, fields, raw = source_record(archive, baseline)
    manifest, samples = inputs(public)
    projected = projections(samples)
    assert (native / "round28-ha-source.pine").read_bytes() == raw
    assert read(native / "round28-ha-feeds.json") == samples
    assert read(work / "round29-ha-js-feeds.json") == projected
    assert (work / "round29-ha-variant.pine").read_bytes() == PINE.encode()
    assert (work / "round29-ha-run.exit").read_text().strip() == "0"
    assert (native / "round28-ha-requests.exit").read_text().strip() == "0"

    native_producer = Path(__file__).with_name(NATIVE)
    assert native_producer.read_bytes() == (native / "r28_ha_requests.py").read_bytes()
    worker = Path(__file__).with_suffix(".mjs")
    assert worker.read_bytes() == (work / "round29-ha-run.mjs").read_bytes()
    assert (
        sha256(native / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    net_isolated = read(native / "round3-isolation-python.json")
    assert all(
        net_isolated[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    js_isolated = read(work / "isolation-probe.json")
    assert js_isolated == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as tar:
        assert (
            tar.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )

    leg = native / "round28-ha-requests-all.json"
    modern = work / "round29-ha-js-receipt.json"
    raw_cases, derived = read(leg), read(modern)

    def index_all(cases):
        target = {(i["period"], i["market"]): i for i in cases}
        assert len(cases) == len(target) == 4
        return target

    merges, trade_cases = map(index_all, (raw_cases, derived))
    meta = {
        "id": IDENT,
        "name": old["name"],
        "source": old["source"],
        "source_sha256": digest,
        "executed_source_sha256": sha256(work / "round29-ha-variant.pine"),
        "group": GROUP,
        "interval": "4h",
        "archive_interval": "4h",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M four-hour OHLCV",
        "comparison_fee": FEE,
        "exit": "Opposite authored smoothed O/C crossing",
    }
    rows, stats = [], []
    for period, markets in samples.items():
        pooled = []
        unsettled = 0
        for m, feed in markets.items():
            key = period, m
            projection = projected[period][m]
            matches = traces(merges[key], feed, projection)
            ledger, terminal, info = orders(trade_cases[key], projection)
            pooled.extend(ledger)
            unsettled += terminal
            stats.append(
                {
                    "id": IDENT,
                    "period": LABEL[period],
                    "market": m,
                    "native_request_series_values_checked": matches,
                    **info,
                }
            )
            rows.append(
                {
                    **meta,
                    "period": LABEL[period],
                    "market": m,
                    **summarize(ledger, terminal, CAPITAL),
                }
            )
        rows.append(
            {
                **meta,
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, unsettled, 2 * CAPITAL),
            }
        )
    input_paths = (
        native / "round28-ha-source.pine",
        native / "round28-ha-feeds.json",
        leg,
        modern,
        work / "round29-ha-js-feeds.json",
        work / "round29-ha-variant.pine",
    )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "source_audit": {
                "document_sha256": digest,
                "settings": fields,
                "author_declaration": "study",
                "has_active_order_calls": True,
                "trade_projection_declaration": "strategy",
            },
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": js_isolated,
            "native_isolation_probe": net_isolated,
            "provider_archives": manifest,
            "artifacts": {
                p.name: sha256(p) for p in (*input_paths, worker, native_producer)
            },
            "method": [
                "The archived v4 study contains two active strategy.entry statements. An isolated original-source prefix exercises its eight request expressions. A separate strategy harness supplies the verified input series to the authored default AVG of length 25 triple TEMA and triple DEMA, then replays its original crossing orders.",
                "The inner daily requests explicitly request source[1]. Under static nested evaluation the outer Heikin Ashi request carries those ordinary-market fields, with the outside request's default end-of-day confirmation. Replacing supplied synthetic OHLC with ordinary OHLC produces identical original request traces on all four histories. A separately calculated one-day lag, with confirmed values forwarded between closes, matches every effective O/C value.",
                "The default filter uses the documented first-non-missing EMA recurrence. The initial five four-hour values remain missing until the outer request can confirm. Piner JS and interpreter executions agree, and independent smoothed series, entry/exit sides, timing, fill prices and terminal positions match every bar and trade.",
                "The original ending timestamp 23:59 marks the final complete UTC trading day for the window. Binance USD-M prices, fixed single units and next-open fills apply. ETH and equal forward windows use independently sourced histories. Before-fee, after-fee, and net of execution-buffer metrics use the same realized fills. Open positions remain unsettled.",
            ],
            "references": [
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/#nested-requests",
                "https://www.tradingview.com/pine-script-reference/v5/#fun_ta.ema",
                "https://www.tradingview.com/support/solutions/43000628599-strategy-properties/",
            ],
            "per_case_order_counts": stats,
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Legacy static daily O/C merge, authored default smoothing, and all actual-market next-open reversals reconcile independently.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"Verified {IDENT}: {len(rows)} workbook rows and {sum(x['closed'] for x in stats)} closed positions."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "native", "public", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    a = parser.parse_args()
    args = (a.archive, a.baseline, a.work, a.native, a.public)
    if a.mode == "stage":
        stage(*args)
    else:
        report(*args, a.output)


if __name__ == "__main__":
    main()
