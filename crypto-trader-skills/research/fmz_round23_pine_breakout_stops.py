"""Reconcile a pinned FMZ 2h breakout strategy's offsets, stops and variable quantities."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from collections import Counter
from hashlib import sha512
from itertools import batched
from math import floor, fsum, isclose
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
    EXECUTION,
    FEE,
    PINER_PIN,
    PINER_VERSION,
    summarize,
    verify_trade,
)
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import average_wilder, equal

IDENT = 4486
CAPITAL = 10_000
GROUP = "FMZ Pine · Native 2h · Verified volume and dynamic breakout orders"
START = "2023-08-12"
END = "2023-09-11"
HOUR = 3_600_000
TICKS = {"BTCUSDT": 0.1, "ETHUSDT": 0.01}

PINE = """//@version=5
strategy("ChannelBreakOutStrategyV2.1")
rstop(value,current) =>
    s = value>1.6?.8:value>=1.4?.85:value>=1.3?.9:.93
    s*current
upBound=ta.highest(high,40)
downBound=ta.lowest(low,40)
volAvg=ta.sma(volume,40)
hasVol=volume/volAvg*100>=120
size=strategy.position_size
hasPos=size!=0
trail=ta.atr(40)*3
basis=strategy.equity-math.max(strategy.openprofit,0)
contracts=math.floor(basis*.03/(trail*syminfo.pointvalue))
realBuy=close-trail
realSell=close+trail
first=not hasPos[1] and hasPos
continues=hasPos[1] and hasPos
var float largest=na
largest := not hasPos or first ? -1 : nz(largest[1])<close ? close : largest[1]
rise=largest/strategy.position_avg_price
var float rbs=na
var float rss=na
rbs := size<=0?realBuy:first?strategy.position_avg_price-trail:rise>=1.3?rstop(rise,largest):continues and realBuy>rbs[1] and close>close[1]?realBuy:rbs[1]
rss := size>=0?realSell:first?strategy.position_avg_price+trail:continues and realSell<rss[1] and close<close[1]?realSell:rss[1]
valid=not na(rbs) and not na(rss)
panicBuy=size>0 and math.max(open-close,0)>=trail/3*2 and rise<1.3
panicSell=size<0 and math.max(close-open,0)>=trail/3*2
if panicBuy
    strategy.close("buy")
    strategy.cancel("exit")
if panicSell
    strategy.close("sell")
    strategy.cancel("exit")
strategy.cancel("buy")
strategy.cancel("sell")
enter=not hasPos and year>2000 and valid and hasVol
if enter
    strategy.order("buy",strategy.long,qty=contracts,stop=upBound+syminfo.mintick*5,comment="BUY")
if rbs>high
    strategy.close("buy")
if size>0 and valid
    strategy.exit("exit","buy",stop=rbs)
if enter
    strategy.order("sell",strategy.short,qty=contracts,stop=downBound-syminfo.mintick*5,comment="SELL")
if rss<low
    strategy.close("sell")
if size<0 and valid
    strategy.exit("exit","sell",stop=rss)
plot(upBound,"High 40")
plot(downBound,"Low 40")
plot(trail,"Trail")
plot(contracts,"Contracts")
plot(enter?1:0,"Enter")
plot(size,"Position")
plot(largest,"Largest")
plot(rbs,"Buy stop")
plot(rss,"Sell stop")
plot(panicBuy?1:0,"Panic buy")
plot(panicSell?1:0,"Panic sell")
plot(strategy.equity,"Equity")
plot(strategy.openprofit,"Open P&L")
plot(strategy.position_avg_price,"Average")
"""


def verify_4486(chart, micro, tick):
    ranges = []
    for i, bar in enumerate(chart):
        p = bar[1] if i == 0 else chart[i - 1][4]
        h, l = bar[2:4]
        ranges.append(max(h - l, abs(h - p), abs(l - p)))
    atr = list(average_wilder(ranges, 40))
    ratio = (chart[1][0] - chart[0][0]) // (micro[1][0] - micro[0][0])
    cash = CAPITAL
    position = None
    queue = None
    protected = None
    panic_close = False
    latest_long = latest_short = None
    largest = None
    held_on_prev_close = False
    trades = []
    witnesses = []
    for i, (bar, intra) in enumerate(zip(chart, batched(micro, ratio), strict=True)):

        def close(j, p, t, why):
            nonlocal cash, position, protected
            side, idx, entry, qty = position
            cash += side * qty * (p - entry) - FEE * qty * p
            trades.append((side, qty, idx, entry, j, p, t, why))
            position = None
            protected = None

        if position and panic_close:
            close(i, bar[1], bar[0], "close signal")
        for time, op, hi, low, _, _ in intra:
            if position and protected is not None:
                side = position[0]
                if side > 0 and low <= protected or side < 0 and hi >= protected:
                    p = min(op, protected) if side > 0 else max(op, protected)
                    close(i, p, time, "rail stop")
            if queue:
                qty, buy, sell = queue
                hit_buy = buy is not None and hi >= buy
                hit_sell = sell is not None and low <= sell
                assert not (hit_buy and hit_sell), (i, time, buy, sell, position)
                if hit_buy or hit_sell:
                    side = 1 if hit_buy else -1
                    p = max(op, buy) if hit_buy else min(op, sell)
                    if position:
                        old_side, _, _, old_qty = position
                        assert old_side == -side and old_qty == qty
                        close(i, p, time, "opposite stop offsets")
                    else:
                        cash -= FEE * qty * p
                        position = side, i, p, qty
                    queue = (qty, None if hit_buy else buy, None if hit_sell else sell)
        _, op, hi, low, mark, volume = bar
        window = chart[max(0, i - 39) : i + 1]
        prior_mark = chart[i - 1][4] if i else None
        high_band = max(c[2] for c in window)
        low_band = min(c[3] for c in window)
        trail = 3 * atr[i] if atr[i] is not None else None
        side, _, entry, qty = position if position else (0, None, None, 0)
        gain = side * qty * (mark - entry) if position else 0.0
        eq = cash + gain
        risk_basis = eq - max(gain, 0)
        count = floor(risk_basis * 0.03 / trail) if trail else None
        first = bool(position and not held_on_prev_close)
        ongoing = position and held_on_prev_close
        largest = (
            -1
            if not position or first
            else max(largest if largest is not None else 0, mark)
        )
        rise = largest / entry if position else None
        rail_buy = mark - trail if trail else None
        rail_sell = mark + trail if trail else None
        if side <= 0:
            long_stop = rail_buy
        elif first:
            long_stop = entry - trail
        elif rise >= 1.3:
            factor = 0.8 if rise > 1.6 else 0.85 if rise >= 1.4 else 0.9
            long_stop = factor * largest
        elif ongoing and rail_buy > latest_long and mark > prior_mark:
            long_stop = rail_buy
        else:
            long_stop = latest_long
        if side >= 0:
            short_stop = rail_sell
        elif first:
            short_stop = entry + trail
        elif ongoing and rail_sell < latest_short and mark < prior_mark:
            short_stop = rail_sell
        else:
            short_stop = latest_short
        valid = long_stop is not None and short_stop is not None
        enter = (
            not position
            and valid
            and volume / (fsum(c[5] for c in window) / 40) * 100 >= 120
        )
        panic_buy = side > 0 and max(op - mark, 0) >= 2 * atr[i] and rise < 1.3
        panic_sell = side < 0 and max(mark - op, 0) >= 2 * atr[i]
        if side > 0:
            panic_close = panic_buy or long_stop > hi
            protected = long_stop
        elif side < 0:
            panic_close = panic_sell or short_stop < low
            protected = short_stop
        else:
            panic_close = False
            protected = None
        queue = (
            (count, high_band + 5 * tick, low_band - 5 * tick)
            if enter and count > 0
            else None
        )
        witnesses.append(
            (
                high_band if i >= 39 else None,
                low_band if i >= 39 else None,
                trail,
                count,
                enter,
                side * qty,
                largest,
                long_stop,
                short_stop,
                panic_buy,
                panic_sell,
                eq,
                gain,
                entry,
            )
        )
        latest_long, latest_short = long_stop, short_stop
        held_on_prev_close = bool(position)
    return trades, witnesses, position


def pinned(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as fmz:
        ((_, _, document, digest),) = documents(fmz, {IDENT: row})
    (block,) = re.findall(
        r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
    )
    settings = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", block
        )
    )
    assert settings == {
        "start": f"{START} 00:00:00",
        "end": f"{END} 00:00:00",
        "period": "2h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert "//@version=2" in block
    active = "\n".join(executable_lines(block))
    assert not re.search(r"\bstrategy\s*\(", active)
    for witness in (
        'title="Length",  minval=1, maxval=1000, defval=40',
        'title = "R",  minval = 1.0, maxval = 10, defval = 3',
        'title = "Auto Adjust R",  defval = false',
        'title = "Volume Threadhold",  minval = 100.0, maxval = 200, defval = 120',
        'title = "Include Long",  defval = true',
        'title = "Include Short",  defval = true',
        'title = "Enable Position Sizing",  defval = true',
        "trailstop = atr(length) * 3",
        "contracts = usePositionSizing == false ? 20 : floor(equity / 100 * curR / (trailstop * ptvalue))",
        "curR = adoptR == false ? maxR",
        "equity = strategy.openprofit > 0 ? strategy.equity - strategy.openprofit : strategy.equity",
        "rbs = strategy.position_size <= 0 ? realbuystop : isPFst ? strategy.position_avg_price - trailstop",
        "rss = strategy.position_size >= 0 ? realsellstop : isPFst ? strategy.position_avg_price + trailstop",
        'strategy.order("buy", strategy.long, qty = contracts, stop=upBound + syminfo.mintick * 5',
        'strategy.order("sell", strategy.short, qty = contracts, stop=downBound - syminfo.mintick * 5',
        'strategy.exit("exit", "buy", stop = rbs, when = hasPos == 1 and isStart == 1)',
        'strategy.exit("exit", "sell", stop = rss, when = hasPos == 1 and isStart == 1)',
        'strategy.cancel("buy")',
        'strategy.cancel("sell")',
    ):
        assert witness in active, witness
    return row, digest, settings, block.encode(), PINE.encode()


def provider_data(public):
    manifest, feeds = [], {}
    begin, end = map(date_ms, (START, END))
    quarter = HOUR // 4
    for market, tick in TICKS.items():
        stream = []
        for month in ("2023-08", "2023-09", "2023-10"):
            name = f"{market}-15m-{month}.zip"
            folder = next(folder for folder in public if (folder / name).is_file())
            (path,) = verified_archives(folder, market, "15m", (month,), manifest)
            stream.extend(provider_bars(path, quarter))
        for label, left, right in (
            ("FMZ native window", begin, end),
            ("Next equal window", end, 2 * end - begin),
        ):
            base = [r for r in stream if left <= r[0] < right]
            assert [r[0] for r in base] == list(range(left, right, quarter))
            assert all(
                isclose(price / tick, round(price / tick), rel_tol=0, abs_tol=1e-8)
                for r in base
                for price in r[1:5]
            )
            chart = aggregate(base, 8)
            feeds.setdefault(label, {})[market] = {
                "chart": [list(r) for r in chart],
                "lower": [list(r) for r in base],
                "frame": "120",
            }
    return manifest, {str(IDENT): feeds}


def stage(archive, baseline, work, public):
    _, _, _, original, variant = pinned(archive, baseline)
    _, feeds = provider_data(public)
    (work / f"risk-stop-source-{IDENT}.pine").write_bytes(original)
    (work / f"risk-stop-variant-{IDENT}.pine").write_bytes(variant)
    copy2(Path(__file__).with_suffix(".mjs"), work / "risk-stop-run.mjs")
    write(work / "risk-stop-feeds.json", feeds)


def runtime(work):
    assert (work / "risk-stop-run.exit").read_text().strip() == "0"
    assert (work / "risk-stop-run.mjs").read_bytes() == Path(__file__).with_suffix(
        ".mjs"
    ).read_bytes()
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as tar:
        assert (
            tar.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    return isolation


def reconcile(case, data):
    chart, base = data["chart"], data["lower"]
    assert not case["requested"]
    actual, signals, open_position = verify_4486(chart, base, TICKS[case["market"]])
    assert case["unsettled"] == int(open_position is not None)
    for i, (known, seen) in enumerate(
        zip(signals, zip(*case["witnesses"], strict=True), strict=True)
    ):
        assert all(equal(x, y) for x, y in zip(known, seen, strict=True)), (
            i,
            known,
            seen,
        )
    events, kinds = [], Counter()
    reversed_ohlc_sequence = 0
    clock = [r[0] for r in chart]
    for expected, trade in zip(actual, case["closed"], strict=True):
        side, qty, entry_bar, entry, exit_bar, out, when, kind = expected
        assert (entry_bar, exit_bar, qty) == (
            trade["entryBar"],
            trade["exitBar"],
            trade["qty"],
        )
        assert trade["entryId"] == ("buy" if trade["dir"] > 0 else "sell")
        if side == trade["dir"]:
            assert equal(entry, trade["entryPrice"]) and equal(out, trade["exitPrice"])
        else:
            assert kind == "opposite stop offsets" and entry_bar == exit_bar
            assert side == -trade["dir"]
            assert equal(entry, trade["exitPrice"]) and equal(out, trade["entryPrice"])
            reversed_ohlc_sequence += 1
        chart_time, gross, fees, execution = verify_trade(trade, clock)
        assert equal(gross, side * qty * (out - entry))
        assert equal(fees, (entry + out) * qty * FEE)
        assert (
            chart_time <= when < chart_time + 2 * HOUR
            and chart[entry_bar][5] > 0
            and chart[exit_bar][5] > 0
        )
        events.append((when, gross, fees, execution))
        kinds[kind] += 1
    return events, {
        "closed": len(events),
        "open_at_cutoff": case["unsettled"],
        "exit_types": dict(kinds),
        "chart_bars": len(chart),
        "subbars": len(base),
        "opposite_stop_sequence_resolved_by_subbars": reversed_ohlc_sequence,
        "entry_ready_instructions": sum(bool(r[4]) for r in signals),
        "nonzero_lot_instructions": sum(bool(r[4]) and r[3] > 0 for r in signals),
        "witnesses_checked": len(signals) * len(case["witnesses"]),
    }


def report(archive, baseline, work, output, public):
    row, digest, settings, raw, variant = pinned(archive, baseline)
    manifest, feeds = provider_data(public)
    assert feeds == read(work / "risk-stop-feeds.json")
    isolation = runtime(work)
    (receipt,) = read(work / "risk-stop-receipt.json")
    assert receipt["id"] == IDENT and "error" not in receipt
    assert receipt["model"]["initialCapital"] == CAPITAL
    assert equal(receipt["model"]["commissionValue"] / 100, FEE)
    source = work / f"risk-stop-source-{IDENT}.pine"
    executed = work / f"risk-stop-variant-{IDENT}.pine"
    assert source.read_bytes() == raw and receipt["sourceHash"] == sha256(source)
    assert executed.read_bytes() == variant and receipt["variantHash"] == sha256(
        executed
    )
    cases = {(r["period"], r["market"]): r for r in receipt["cases"]}
    assert len(cases) == len(receipt["cases"]) == 4
    common = {
        "id": IDENT,
        "name": row["name"],
        "source": row["source"],
        "source_sha256": digest,
        "executed_source_sha256": receipt["variantHash"],
        "interval": "2h",
        "archive_interval": "15m",
        "quote_currency": "USDT",
        "group": GROUP,
        "market_data": "Official Binance USD-M historical 15m bars",
        "exit": "Authored ATR ratchet stop, panic market close or opposite stop netting",
    }
    results, counts = [], []
    for period, markets in feeds[str(IDENT)].items():
        combined, open_positions = [], 0
        for market, data in markets.items():
            case = cases[(period, market)]
            events, proof = reconcile(case, data)
            counts.append({"period": period, "market": market, **proof})
            combined.extend(events)
            open_positions += case["unsettled"]
            results.append(
                {
                    **common,
                    "period": period,
                    "market": market,
                    **summarize(events, case["unsettled"], CAPITAL),
                }
            )
        results.append(
            {
                **common,
                "period": period,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(combined, open_positions, 2 * CAPITAL),
            }
        )
    closed = sum(r["closed"] for r in counts)
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
                for name in (
                    "risk-stop-feeds.json",
                    "risk-stop-run.mjs",
                    "risk-stop-receipt.json",
                )
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "initial_comparison_capital": CAPITAL,
                "point_value_per_base_unit": 1,
                "minimum_price_tick": TICKS,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "FMZ permits omitted Pine declarations. The source declaration with fee and fill recalculation is commented. This historical breakout comparison uses 10,000 USDT balance, closed-bar calculations and a 0.059% fee per fill. The broker uses one USDT of P&L per one USDT price move per base unit, and uses the same exact exchange price tick observed in the archive.",
                "The source defaults activate both directions and dynamic integer sizing at 3% equity risk relative to the 3×ATR(40) distance. The independent broker recalculates the account and deducts current open gains from its risk sizing basis. It preserves the 120% average-volume gate, 40-bar range, offset of five ticks, prior pending order replacement, and the authored directional trailing stop for each side.",
                "The source reuses a single exit identifier. The migration issues that instruction for the current matching buy or sell entry. It preserves the authored stop calculations and panic checks. Market close orders take the next open. One ETH chart bar reaches both entry levels. Separate 15-minute timestamps resolve its sell-then-buy order, while the coarse Pine emulator uses the opposite order. Both paths transact the same two prices and have identical cashflows.",
                "The actual archive is the BTC comparison. ETH is a same-market-family comparison with its own prices. The chronological forward window starts with clean state. The discounted comparison net uses a separate 0.03% buffer per fill. Counts and P&L include realized trades and preserve open positions at cutoff.",
            ],
            "source_audits": {
                IDENT: {
                    "archive_settings": settings,
                    "source_document_sha256": digest,
                    "closed": closed,
                }
            },
            "per_case_order_counts": counts,
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Validated the actual archived dynamic breakout quantities, priced-order lifecycles, protective rails, panic closes and historical net cashflows.",
                ]
            ],
            "results": results,
        },
    )
    print(f"Verified {len(results)} rows and {closed} closed positions.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("stage", stage), ("finalize", report)):
        cmd = commands.add_parser(name)
        for arg in ("archive", "baseline", "work"):
            cmd.add_argument(arg, type=Path)
        if name == "finalize":
            cmd.add_argument("output", type=Path)
        cmd.add_argument("public", type=Path, nargs="+")
        cmd.set_defaults(handler=handler)
    cfg = vars(parser.parse_args())
    cfg.pop("command")
    cfg.pop("handler")(**cfg)


if __name__ == "__main__":
    main()
