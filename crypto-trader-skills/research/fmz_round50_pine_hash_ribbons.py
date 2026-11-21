"""Verify a source-author-supported historical Bitcoin hashrate provider variant."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from math import isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 4802
DAY = 86_400_000
HOUR = 3_600_000
CAPITAL = 1_000_000
PROBE = "fmz_round50_pine_hash_ribbons_probe.py"
BEGIN, CUT = map(date_ms, ("2023-01-05", "2024-01-11"))
STOP = 2 * CUT - BEGIN
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
PROVIDERS = {
    "Blockchain.com": {
        "file": "4802-blockchain.raw",
        "sha256": "be9c9f7bf7ea17985fe75266274ba397dd1b83e578dee203eafb0e594374be2b",
        "url": "https://api.blockchain.info/charts/hash-rate?format=json&sampled=false&start=2022-11-01&timespan=810days",
        "observations": 811,
    },
    "Coin Metrics": {
        "file": "4802-coinmetrics.raw",
        "sha256": "41f5647499ca01937c55b047dc1ff55e1190949e0b8e4b87baae972299d82c47",
        "url": "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=HashRate&frequency=1d&start_time=2022-11-01&end_time=2025-01-18&page_size=10000",
        "observations": 810,
    },
}


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (root,) = (row for row in read(baseline)["disposition"] if row["id"] == IDENT)
    assert root["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, digest),) = documents(book, {IDENT: root})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2023-01-05 00:00:00",
        "end": "2024-01-11 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    pine, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert count == 1
    for anchor in (
        "//@version=5",
        'strategy("BTC Hashrate ribbons", overlay = true)',
        "enableDirection = input(0",
        'defval="SMA"',
        "SmoothLengthS = input(30",
        "SmoothLengthL = input(60",
        'HashRate = request.security("INTOTHEBLOCK:BTC_HASHRATE", "D", close)',
        "LongCondition = ta.crossover(SignalLine, LongLine)",
        "ShortCondition = ta.crossunder(SignalLine, LongLine)",
        'strategy.entry("Long", strategy.long)',
        'strategy.entry("Short", strategy.short)',
    ):
        assert anchor in pine
    return root, digest, fields, pine


def inputs(provider_root, daily, hourly):
    series = {"source": {}, "values": {}}
    for name, meta in PROVIDERS.items():
        path = provider_root / meta["file"]
        assert sha256(path) == meta["sha256"]
        raw = read(path)
        if name == "Blockchain.com":
            assert (
                raw["status"] == "ok"
                and raw["period"] == "day"
                and raw["unit"] == "Hash Rate TH/s"
            )
            value_map = {x["x"] * 1000: x["y"] for x in raw["values"]}
        else:
            assert "next_page_url" not in raw and all(
                x["asset"] == "btc" for x in raw["data"]
            )
            value_map = {
                int(datetime.fromisoformat(x["time"]).timestamp()) * 1000: float(
                    x["HashRate"]
                )
                for x in raw["data"]
            }
        assert len(value_map) == meta["observations"]
        assert sorted(value_map) == list(range(min(value_map), max(value_map) + 1, DAY))
        assert all(x > 0 for x in value_map.values())
        series["source"][name] = meta["sha256"]
        series["values"][name] = [
            [t, value_map[t - DAY]] for t in range(BEGIN, STOP, DAY)
        ]

    market = {}
    evidence = []
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(BEGIN, STOP, DAY)
        }
    )
    for coin in ("BTC", "ETH"):
        pair = coin + "USDT"
        days = {
            x[0]: list(x) for x in cache_bars(daily, pair, "1d", months, DAY, evidence)
        }
        hours = {
            x[0]: x[1]
            for x in cache_bars(hourly, pair, "1h", months, HOUR, evidence)
            if x[0] % DAY == 0
        }
        for tag, lo, hi in (("native", BEGIN, CUT), ("next", CUT, STOP)):
            bars = [days[t] for t in range(lo, hi, DAY)]
            assert all(x[1] == hours[x[0]] for x in bars)
            market.setdefault(tag, {})[coin] = bars
    return {"series": series, "chart": market, "archives": evidence}


def verify(pack, receipt):
    provider, coin, period, diagnostics, native, plots, _ = receipt
    assert not diagnostics and not native["diagnostics"]
    chart = pack["chart"][period][coin]
    marks = dict(pack["series"]["values"][provider])
    observed = [marks[b[0]] for b in chart]
    assert all(a == b for a, b in zip(observed, plots["Raw"], strict=True))
    simple = {
        "Short MA": [
            sum(observed[max(0, i - 29) : i + 1]) / 30 if i >= 29 else None
            for i in range(len(chart))
        ],
        "Long MA": [
            sum(observed[max(0, i - 59) : i + 1]) / 60 if i >= 59 else None
            for i in range(len(chart))
        ],
    }
    for label, calculated in simple.items():
        assert all(
            a is None
            and b is None
            or a is not None
            and b is not None
            and isclose(a, b, rel_tol=1e-12)
            for a, b in zip(calculated, plots[label], strict=True)
        )
    decisions = []
    orders = []
    for i, (a, b) in enumerate(zip(simple["Short MA"], simple["Long MA"], strict=True)):
        side = 0
        if i >= 60:
            a0, b0 = simple["Short MA"][i - 1], simple["Long MA"][i - 1]
            side = 1 if a0 <= b0 and a > b else -1 if a0 >= b0 and a < b else 0
        assert bool(plots["Long"][i]) == (side > 0) and bool(plots["Short"][i]) == (
            side < 0
        )
        if side:
            decisions.append([chart[i][0], side])
            if i + 1 < len(chart):
                orders.append((i + 1, side, chart[i + 1][1]))
    for i, (entry, (j, d, px)) in enumerate(zip(native["orders"], orders, strict=True)):
        assert (entry["barIndex"], entry["price"], entry["id"]) == (
            j,
            px,
            "Long" if d > 0 else "Short",
        )
        assert entry["qty"] == (1 if i == 0 else 2)
    flows = []
    for trade, (start, d, entry), (end, _, exit) in zip(
        native["trades"], orders[:-1], orders[1:], strict=True
    ):
        gross = d * (exit - entry)
        assert (trade["entryBarIndex"], trade["exitBarIndex"], trade["qty"]) == (
            start,
            end,
            d,
        )
        assert (trade["entryPrice"], trade["exitPrice"], trade["profit"]) == (
            entry,
            exit,
            gross,
        )
        notional = entry + exit
        flows.append((chart[end][0], gross, notional * FEE, notional * EXECUTION))
    book = CAPITAL
    hold = origin = 0
    due = {i: (d, p) for i, d, p in orders}
    for i, bar in enumerate(chart):
        if i in due:
            d, p = due[i]
            book += hold * (p - origin)
            hold, origin = d, p
        mark = book + hold * (bar[4] - origin)
        assert isclose(mark, native["equity"][i]["equity"], rel_tol=1e-12, abs_tol=1e-7)
    assert len(decisions) == 6 and len(orders) == 6 and len(flows) == 5 and hold
    return flows, decisions


def stage(args, source, data):
    args.work.mkdir(parents=True, exist_ok=True)
    (args.work / "round47-4802.pine").write_text(source, encoding="utf8", newline="\n")
    write(args.work / "round47-4802-feeds.json", data)
    copy2(Path(__file__).with_name(PROBE), args.work / PROBE)


def report(args, root, digest, fields, source, data):
    w = args.work
    runtime = w / "priced-runtime/pine_compat/pine_compat.pyd"
    native = w / "round47-4802-receipt.json"
    worker = Path(__file__).with_name(PROBE)
    assert sha256(runtime) == NATIVE_BINARY_HASH and sha256(worker) == sha256(w / PROBE)
    isolate = read(w / "round3-isolation-python.json")
    assert all(
        isolate[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    assert (w / "round47-4802.pine").read_text(encoding="utf8") == source
    assert read(w / "round47-4802-feeds.json") == data
    sessions = read(native)
    assert len(sessions) == 8
    prices, decisions, hashes = {}, {}, {}
    for receipt in sessions:
        provider, coin, period, *_ = receipt
        flows, gates = verify(data, receipt)
        pair = coin, period
        assert prices.setdefault(pair, flows) == flows
        assert decisions.setdefault(period, gates) == gates
        assert hashes.setdefault(provider, receipt[-1]) == receipt[-1]
    assert len(prices) == 4 and len(hashes) == 2 and len(decisions) == 2
    rows = []
    info = {
        "id": IDENT,
        "source": root["source"],
        "source_sha256": digest,
        "executed_source_sha256": hashes["Blockchain.com"],
        "group": "FMZ Pine · Blockchain.com BTC hash-rate variant",
        "interval": "1d",
        "archive_interval": "1h",
        "currency": "USDT",
        "quote_currency": "USDT",
        "market_data": "Official Binance BTC/ETH USD-M 1d/1h and public Blockchain.com BTC network hashrate",
        "exit": "Opposite 30/60 Bitcoin hashrate SMA crossover at next daily open",
    }
    for window, label in LABEL.items():
        pooled = []
        for coin in ("BTC", "ETH"):
            flows = prices[coin, window]
            pooled.extend(flows)
            rows.append(
                {
                    **info,
                    "period": label,
                    "market": coin + "USDT",
                    **summarize(flows, 1, CAPITAL),
                }
            )
        rows.append(
            {
                **info,
                "period": label,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, 2, 2 * CAPITAL),
            }
        )
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": digest,
            "archived_settings": fields,
            "input_providers": PROVIDERS,
            "market_archives": data["archives"],
            "native_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolate,
            "worker_sha256": sha256(worker),
            "worker_receipt_sha256": sha256(native),
            "provider_executed_source_hashes": hashes,
            "equal_signal_schedule": decisions,
            "cost_model": {
                "original_fee_per_side": 0,
                "comparison_fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
            },
            "verification": {
                "matched_asset_windows": 4,
                "independent_provider_market_replays": 8,
                "source_main_dated_bars": 4 * 371,
                "closed_lots_count": 20,
                "same_provider_signals_and_fills": True,
            },
            "method": [
                "The archived order logic remains unchanged. Its literal IntoTheBlock symbol is replaced with a named provider symbol. The script author published alternative Glassnode and Nasdaq/Quandl releases. This variant uses direct Blockchain.com daily Bitcoin network hashrate and checks it against official Coin Metrics daily Bitcoin observations; the original IntoTheBlock dataset was unavailable.",
                "Each UTC market day sees at most the prior dated hash-rate sample. The release used the original 30/60 SMA and both long/short defaults, plus independent daily windows of 371 bars each. Both data sources produced the same six actual crossovers and next-open fills in each window. ETH is tested against the script's authored Bitcoin network factor.",
                "Each official Binance USD-M daily opening price matches its independent 1h base opening tick. Both provider paths match independently calculated SMA series, crosses, every historical order, trade profit and marked ledger using the runtime's default 1-unit size and 1,000,000 USDT model equity. Fee and execution adjustments are applied afterward. Net funding and liquidation are outside this model.",
            ],
            "references": [
                "https://www.fmz.com/strategy/438471",
                "https://www.tradingview.com/script/w6QJPRr3-BTC-Hashrate-ribbons/",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/#requestquandl",
                "https://www.blockchain.com/explorer/charts/hash-rate",
                "https://docs.coinmetrics.io/network-data/network-data-overview/mining",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    "Tested · FMZ public hashrate provider variant",
                    "The source-author-supported public provider variant has two independent daily BTC hashrate estimates with all twelve signals, native orders, P&L and equity identical across archived and next BTC/ETH windows. Exact IntoTheBlock archive remains unavailable.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"{len(rows)} rows, 8 checked provider paths, 20 nonpooled closed trades, four terminal units"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "report"))
    for field in ("archive", "baseline", "work", "provider_root", "out"):
        parser.add_argument(field, type=Path)
    for key in ("daily", "hourly"):
        parser.add_argument(f"--{key}", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    root, digest, fields, source = source_record(args.archive, args.baseline)
    data = inputs(args.provider_root, args.daily, args.hourly)
    if args.mode == "stage":
        stage(args, source, data)
    else:
        report(args, root, digest, fields, source, data)


if __name__ == "__main__":
    main()
