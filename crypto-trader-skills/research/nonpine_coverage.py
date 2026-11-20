"""Assemble the non-FMZ replay and per-catalogue-ID dependency accounting."""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent
ARTIFACTS = (
    "freq-out.jsonl",
    "freq-a-out.jsonl",
    "freq-b-out.jsonl",
    "freq-all-out.jsonl",
    "jesse-out.jsonl",
    "legacy-out.jsonl",
    "tv-binance-variants.jsonl",
)
REJECTED_NATIVE = {
    5813: "The archived custom-stop source omits a timeframe and uses a pandas Index.get_loc API that the current engine no longer exposes.",
    5814: "The pinned GodStra source imports numpy.lib.math, which NumPy 2 removed. No source migration was verified.",
    5830: "The spot-mode run fell back to an incomplete market context because the pinned strategy requires separate BTC perpetual informative candles.",
    5863: "The pinned FOttStrategy source imports numpy.lib.math, which NumPy 2 removed. No source migration was verified.",
    5875: "The pinned multi-timeframe strategy was not loadable in Freqtrade 2026.10. Its informative routes also require ETH/BTC market data.",
}
PROTOCOL = (
    (
        6151,
        "Pendle pool maturity, entry price, PT/YT/SY trades, liquidity and redemption fees",
    ),
    (
        6154,
        "Boros tenor-specific fixed rates, actual floating payments and historical position quotes",
    ),
    (
        6157,
        "Meteora pool and range, executable bin liquidity, swap/fee events and rebalancing rules",
    ),
    (
        6159,
        "Liquity liquidation, stability-pool or redemption events and executable LUSD and collateral prices",
    ),
    (
        6161,
        "Ribbon epoch, option auction premium and strike, redemption and vault fees",
    ),
    (
        6164,
        "Bybit historical subscribed products, offered terms, yields, barrier settlement and entry rules",
    ),
    (
        6168,
        "OKX terms at subscription, observed reference levels, barrier and settlement history",
    ),
    (
        6170,
        "Executable DVol futures and option prices, contract rolls and hedge entry/exit rules",
    ),
    (
        6171,
        "LP reserves, minted and burned shares, fees and matching GammaSwap hedge costs",
    ),
    (6174, "Opyn position, funding, collateral and unwind before the Squeeth shutdown"),
    (6175, "Luxor forward quotes, terms, hashprice fixing and hedge dates"),
    (
        6176,
        "Alkimiya orders and settlement cash flows plus matching blockspace fee history",
    ),
    (
        6179,
        "A defined Polymarket event and signal plus synchronized executable prices, fees and resolution",
    ),
    (6181, "GM/GLV assets, share mint/burn quotes, inventory, P&L and fees"),
    (
        6182,
        "Notional borrowing rates, collateral, cash flows, points conversion and fees",
    ),
    (
        6183,
        "Lido vault settings, liquidation thresholds, staking returns, rates and transaction costs",
    ),
    (
        6184,
        "Curve incentives, governance vote weights, eligibility and rotation schedule",
    ),
)
FEEDS = {
    5962: "Archived AI predictions and matching model configuration",
    5963: "Native position executor and candle configuration for Bollinger directional controller",
    5964: "Native position executor and candle configuration for Bollinger directional controller",
    5966: "DCA price ladder and native executor fill and inventory accounting",
    5967: "Native MACD/Bollinger indicator and triple-barrier executor parity",
    5968: "Native Supertrend, executor lifecycle and exit/fill parity",
    5969: "Synchronized executable quotes on both configured venues and a latency and fill model",
    5970: "Example single-order executor needs an exit rule",
    5971: "Example order lifecycle needs a start time and connector/order settings",
    5972: "Example order scheduler needs a start time and liquidation rules",
    5973: "Candle-feed example needs a complete order lifecycle",
    5974: "Configured execution triggers, order sizes and native executor parity",
    5975: "Liquidation monitor needs order entry and exit rules",
    5976: "Market status example needs a trade trigger",
    5977: "Price monitor needs order entry and exit rules",
    5979: "Portfolio and hedge inventory, market quotes and rebalance settings",
    5980: "Chain/pool states, token balances, rebalancing triggers and transaction costs",
    5985: "Configured pair and hedge series and synchronized executable prices",
    5990: "Synchronized AMM quotes, gas and centralized order-book data with settlement timing",
    5994: "Portfolio and hedge inventory, market quotes and rebalance settings",
    5998: "Synchronized spot/perpetual depth, funding, simultaneous fills and capacity",
    6000: "Dip analyser evaluator configuration and a downstream trading mode",
    6001: "Component evaluator settings, synchronization and a downstream trading mode",
    6002: "Component evaluator feeds and a downstream trading mode",
    6003: "Synchronized venue quotes and executable size for OctoBot arbitrage",
    6005: "Upstream evaluator outputs, initial portfolio and order controls",
    6006: "Order ladder, quote budget, resting-order fills and exits",
    6007: "Dip analyser evaluator signals and resting sell-order lifecycle",
    6008: "Grid levels, inventory and resting-order fills",
    6009: "Index constituent universe, weights, execution prices and rebalancing controls",
    6010: "Market depth, inventory, resting-order fills and cancel/repost timing",
    6011: "Historical remote signal alerts and order settings",
    6012: "Concrete evaluator tentacle outputs and order settings",
    6013: "Staggered order ladder, inventory and resting-order fills",
    6014: "Historical TradingView alert messages, event timing and order settings",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def deps(i, source, previous, tv):
    if source == "TradingView":
        return tv[i]
    if source == "Protocol & venue playbooks":
        return "Protocol history and rules needed", "Needs " + next(
            reason for last, reason in PROTOCOL if i <= last
        )
    if source == "Deribit":
        terms = "contract expiries" if i == 6054 else "strikes and expiries"
        return "Options or futures execution needed", (
            f"Public Deribit prints and listed combinations were accessible. Needs {terms}, "
            "entry and exit rules, and synchronized executable quotes for the chosen combination."
        )
    if source in ("hummingbot", "OctoBot-Tentacles"):
        return "Framework inputs needed", FEEDS.get(
            i,
            "Requires historical depth, inventory, order queue/fill state and configured venue-specific executor data",
        )
    if source == "example-strategies":
        return (
            "Jesse replay pending",
            "Pinned Jesse callbacks require a verified research-engine replay",
        )
    if source == "freqtrade-strategies" and previous[4] != "Needs execution model":
        return (
            "Freqtrade replay pending",
            "Pinned strategy requires a verified native backtest",
        )
    if i == 5879:
        return (
            "Legacy adapter rejected source signal",
            "Zenbot dema emits 'sold' on an overbought event. The isolated adapter requires the engine's buy/sell signal contract.",
        )
    if i == 5893:
        return (
            "Legacy engine state needed",
            "Zenbot RSI imports the engine and reads asset_capital and currency_capital when deciding advice.",
        )
    return previous[4], previous[5]


def finish(work, workbook, output):
    with (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as f:
        stock = list(csv.DictReader(f))
    wb = load_workbook(workbook, read_only=True, data_only=True)
    candidates = {
        r[0]: r
        for r in wb["Test coverage"].values
        if r
        and isinstance(r[0], int)
        and r[2] not in ("FMZ", "Jesse reports")
        and not r[4].startswith("Tested")
        and r[4] != "Excluded"
    }
    wb.close()
    assert len(candidates) == 231, len(candidates)
    pages = read(work / "tv-pending.json")
    tradingview_methods = read(work / "tv-methods.json")
    tv = {i: (status, detail) for i, status, detail, _ in pages}
    records = {}
    for artifact in ARTIFACTS:
        path = work / artifact
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            record = json.loads(line)
            if artifact == "tv-binance-variants.jsonl":
                for row in record.get("results", []):
                    market = {
                        "BTCUSD": "BTC/USDT perp",
                        "ETHUSD": "ETH/USDT perp",
                        "BTC + ETH": "BTC + ETH perp",
                    }[row["market"]]
                    group = (
                        "TradingView documented rules · Binance"
                        if row["id"] >= 6040
                        else "TradingView · Binance"
                    )
                    row.update(
                        group=group,
                        market=market,
                        venue="Binance USD-M perpetual",
                        currency="USDT",
                        archive_interval="Chart timeframe",
                        funding_model="Chart-price study with commission and estimated execution cost",
                    )
                    if method := tradingview_methods.get(str(row["id"])):
                        row["source_adaptation"] = method
                    if row["id"] >= 6040:
                        row["exit"] = "Documented opposite-signal reversal"
            records[record["id"]] = record
    assert records.keys() <= candidates.keys(), records.keys() - candidates.keys()
    coverage, results = [], []
    for i, previous in sorted(candidates.items()):
        row = stock[i - 1]
        assert row["name"] == previous[1] and row["source"] == previous[2], i
        record = records.get(i, {})
        if i in REJECTED_NATIVE:
            status, message = "Replay rejected", REJECTED_NATIVE[i]
        elif detail := record.get("results"):
            assert len(detail) == 6 and {r["period"] for r in detail} == {
                "Reference",
                "Later",
            }, i
            for trade in detail:
                assert (
                    abs(trade["gross"] - trade["fees"] - trade["after_fees"]) < 1e-6
                ), i
                assert (
                    abs(
                        trade["after_fees"]
                        + trade.get("funding", 0.0)
                        - trade["execution"]
                        - trade["net"]
                    )
                    < 1e-6
                ), i
            results.extend(detail)
            group = detail[0]["group"]
            status = (
                f"Tested · {group}"
                if any(r["trades"] for r in detail)
                else "Tested · no closes"
            )
            message = f"{group} on BTC and ETH, {detail[0]['interval']} source or declared chart timeframe"
        elif error := record.get("reason"):
            status, message = "Replay rejected", error
        else:
            status, message = deps(i, row["source"], previous, tv)
        coverage.append([i, status, message])
    files = read(work / "binance/manifest.json")
    for file in (work / "binance").glob("funding-*-nov.json"):
        coin = file.name.split("-")[1]
        url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={coin}&startTime=1793491200000&endTime=1793836800000"
        files[file.name] = {
            "sha256_or_error": hashlib.sha256(file.read_bytes()).hexdigest(),
            "url": url,
        }
    archive_files = (
        work / "freq.zip",
        work / "example.zip",
        work / "hb.zip",
        *sorted((work / "legacy").glob("*.zip")),
    )
    report = dict(
        coverage=coverage,
        rows=results,
        market_data=files,
        periods_ist={
            "Reference": ["2026-09-23", "2026-10-21"],
            "Later": ["2026-10-21", "2026-11-04"],
        },
        engine={
            "TradingView": "PineTS 0.13.1",
            "Freqtrade": "Freqtrade 2026.10",
            "Jesse": "Jesse 3.6.1",
        },
        archive_sha256={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in archive_files
            if p.exists()
        },
        tradingview_help={str(i): url for i, _, _, url in pages},
        tradingview_methods=tradingview_methods,
        deribit_probe={
            "currency": "BTC",
            "instrument": "BTC-22OCT26-84000-C",
            "trade_timestamp_ms": 1792627222278,
            "url": "https://history.deribit.com/api/v2/public/get_last_trades_by_currency_and_time?currency=BTC&start_timestamp=1792627200000&end_timestamp=1792630800000&kind=option&count=1&sorting=asc",
        },
    )
    output.write_text(
        json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    print(Counter(r[1] for r in coverage), len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    finish(args.work, args.workbook, args.output)
