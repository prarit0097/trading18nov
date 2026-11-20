from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import logging
import math
import sys
import warnings
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "freq-addons"), str(ROOT / "deps")]

import pandas as pd
from freqtrade.configuration import TimeRange
from freqtrade.data.history import get_datahandler
from freqtrade.enums import CandleType, MarginMode, RunMode, TradingMode
from freqtrade.exchange.binance import Binance
from freqtrade.exchange import timeframe_to_seconds
from freqtrade.optimize.backtesting import Backtesting

ARCHIVE = ROOT / "freq.zip"
CANDLES = ROOT / "binance"
DATADIR = ROOT / "freqdata"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SPOT_PAIRS = ("BTC/USDT", "ETH/USDT")
FUTURE_PAIRS = tuple(p + ":USDT" for p in SPOT_PAIRS)
IST = timezone(timedelta(hours=5, minutes=30))
WINDOWS = {
    "Reference": ("2026-09-23", "2026-10-21"),
    "Later": ("2026-10-21", "2026-11-04"),
}
TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d")
FEE = 0.00059
EXECUTION = 0.00030
EQUITY = 10000
STAKE = 1000
EXCLUDED = {5845, 5847, 5870, 5871, 5872, 5873}
EXECUTION_REQUIRED = {5808, 5829}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def stamp(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=IST).timestamp())


def unzip_rows(path):
    with ZipFile(path) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0].endswith(".csv"), path.name
        with z.open(names[0]) as f:
            yield from csv.reader(io.TextIOWrapper(f, encoding="utf-8"))


def parse_candles(pattern, minutes):
    sample = []
    for path in sorted(CANDLES.glob(pattern)):
        for row in unzip_rows(path):
            if row[0].isdigit():
                raw_time = int(row[0])
                millis = raw_time // 1000 if raw_time >= 10**15 else raw_time
                sample.append((millis, *map(float, row[1:6])))
    cols = ["date", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(sample, columns=cols).sort_values("date").reset_index(drop=True)
    assert len(df) > 0 and (df.date.diff().iloc[1:] == minutes * 60000).all(), pattern
    assert (df.low > 0).all() and ((df.low <= df.open) & (df.low <= df.close)).all()
    assert ((df.high >= df.open) & (df.high >= df.close) & (df.volume >= 0)).all()
    df["date"] = pd.to_datetime(df.date, unit="ms", utc=True)
    return df


def resample(df, timeframe):
    minutes = timeframe_to_seconds(timeframe) // 60
    if minutes == 1:
        return df
    groups = df.set_index("date").resample(f"{minutes}min")
    bins = groups.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return bins[groups.size().eq(minutes)].reset_index()


def funding(symbol):
    sample = [
        (int(row[0]), float(row[2]))
        for path in CANDLES.glob(f"fundingRate-futures-{symbol}-*.zip")
        for row in unzip_rows(path)
        if row[0].isdigit()
    ]
    prices = read(CANDLES / f"funding-{symbol}-nov.json")
    sample += [(int(r["fundingTime"]), float(r["fundingRate"])) for r in prices]
    values = {int(round(t / 28800000)) * 28800000: rate for t, rate in sample}
    times = sorted(values)
    assert min(times) <= stamp(WINDOWS["Reference"][0]) * 1000
    assert max(times) >= stamp(WINDOWS["Later"][1]) * 1000
    assert all(b - a == 28800000 for a, b in zip(times, times[1:])), symbol
    rows = [(t, values[t], values[t], values[t], values[t], 0.0) for t in times]
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df.date, unit="ms", utc=True)
    df["funding_rate"] = df["open"]
    return df


def prepare_data():
    DATADIR.mkdir(exist_ok=True)
    handler = get_datahandler(DATADIR, "feather")
    meta = {}
    for market, contracts, candle_type in (
        ("spot", SPOT_PAIRS, CandleType.SPOT),
        ("futures", FUTURE_PAIRS, CandleType.FUTURES),
    ):
        for symbol, pair in zip(SYMBOLS, contracts):
            df = parse_candles(f"klines-{market}-{symbol}-1m-*.zip", 1)
            meta[pair] = {
                "first_utc": df.date.iloc[0].isoformat(),
                "last_utc": df.date.iloc[-1].isoformat(),
                "size_1m": len(df),
            }
            assert (df.volume > 0).all(), pair
            for interval in TIMEFRAMES:
                handler.ohlcv_store(pair, interval, resample(df, interval), candle_type)
            if market == "futures":
                handler.ohlcv_store(
                    pair,
                    "1h",
                    parse_candles(f"markPriceKlines-futures-{symbol}-1h-*.zip", 60),
                    CandleType.MARK,
                )
                handler.ohlcv_store(
                    pair, "1h", funding(symbol), CandleType.FUNDING_RATE
                )
    (ROOT / "freqdata-meta-v2.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )


def native_market(config, futures, max_leverage=1):
    exchange = Binance(config, validate=False)
    raw = read(ROOT / ("futures-exchange.json" if futures else "spot-exchange.json"))
    exchange._api.options["crossMarginPairsData"] = []
    exchange._api.options["isolatedMarginPairsData"] = []
    markets = [
        exchange._api.parse_market(item)
        for item in raw["symbols"]
        if item["symbol"] in (*SYMBOLS, "ETHBTC")
    ]
    exchange._api.set_markets(markets)
    exchange._api_async.set_markets_from_exchange(exchange._api)
    exchange._markets = exchange._api.markets
    if futures:
        # The single modeled tier serves BTC/ETH positions at the $1,000 stake cap.
        for pair in FUTURE_PAIRS:
            exchange._leverage_tiers[pair] = [
                dict(
                    minNotional=0,
                    maxNotional=100000,
                    maintenanceMarginRate=0.005,
                maxLeverage=max_leverage,
                    maintAmt=0,
                )
            ]
    return exchange


def candidate_sources(stock):
    strategy_root = ROOT / "freqsrc"
    strategy_root.mkdir(exist_ok=True)
    with ZipFile(ARCHIVE) as z:
        names = {name.split("/", 1)[1]: name for name in z.namelist() if "/" in name}
        for item in stock:
            ident = item["id"]
            if ident in EXCLUDED or ident in EXECUTION_REQUIRED:
                continue
            path = item["source_url"].split(
                "/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/", 1
            )[1]
            code = z.read(names[path])
            classes = [
                c
                for c in ast.parse(code).body
                if isinstance(c, ast.ClassDef)
                and any(
                    isinstance(b, ast.Name) and b.id == "IStrategy" for b in c.bases
                )
            ]
            if len(classes) != 1:
                yield item, None, None, None
                continue
            group = strategy_root / str(ident)
            group.mkdir(exist_ok=True)
            (group / Path(path).name).write_bytes(code)
            params = names.get(path.removesuffix(".py") + ".json")
            if params:
                (group / (Path(path).stem + ".json")).write_bytes(z.read(params))
            attrs = {
                n.targets[0].id: n.value
                for n in classes[0].body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            }
            methods = {
                n.name for n in classes[0].body if isinstance(n, ast.FunctionDef)
            }
            futures = (
                "/futures/" in path
                or ast.unparse(attrs.get("can_short", ast.Constant(False))) == "True"
            )
            if futures and (
                "leverage" in methods or "adjust_trade_position" in methods
            ):
                yield (
                    item,
                    classes[0].name,
                    "complex_futures",
                    hashlib.sha256(code).hexdigest(),
                )
                continue
            yield (
                item,
                classes[0].name,
                "futures" if futures else "spot",
                hashlib.sha256(code).hexdigest(),
            )


def summary(item, market, period, interval, source_hash, sample, unsettled):
    cash = [0.0] * 3
    wins = [0] * 3
    peak = [EQUITY] * 3
    dd = [0.0] * 3
    dd_pct = [0.0] * 3
    by_time = defaultdict(lambda: [0.0] * 3)
    funding_total = 0.0
    for timestamp, gross, fee_only, net, funding_cash in sample:
        funding_total += funding_cash
        for slot, val in enumerate((gross, fee_only, net)):
            by_time[timestamp][slot] += val
            wins[slot] += val > 1e-9
    for _, pnl in sorted(by_time.items()):
        for slot, val in enumerate(pnl):
            cash[slot] += val
            equity = EQUITY + cash[slot]
            peak[slot] = max(peak[slot], equity)
            dd[slot] = max(dd[slot], peak[slot] - equity)
            dd_pct[slot] = max(dd_pct[slot], (peak[slot] - equity) / peak[slot])
    return dict(
        group="Freqtrade · Binance",
        name=item["name"],
        market=market,
        exit="Source Freqtrade exits",
        period=period,
        trades=len(sample),
        unsettled=unsettled,
        gross_wins=wins[0],
        fee_wins=wins[1],
        net_wins=wins[2],
        gross=cash[0],
        after_fees=cash[1],
        net=cash[2],
        fees=cash[0] - cash[1],
        execution=cash[1] - cash[2] + funding_total,
        funding=funding_total,
        gross_dd=dd[0],
        fee_dd=dd[1],
        net_dd=dd[2],
        gross_dd_pct=dd_pct[0],
        fee_dd_pct=dd_pct[1],
        net_dd_pct=dd_pct[2],
        id=item["id"],
        source=item["source_url"],
        source_sha256=source_hash,
        archive_interval=interval,
        interval=interval,
        venue="Binance USD-M perpetual" if market.endswith("perp") else "Binance spot",
        currency="USDT",
    )


def analyze(item, name, mode, source_hash, label, dates, *, order_ledger=None, max_leverage=1):
    is_futures = mode == "futures"
    pairs = FUTURE_PAIRS if is_futures else SPOT_PAIRS
    margin_mode = MarginMode.ISOLATED if is_futures else MarginMode.NONE
    config = dict(
        strategy=name,
        user_data_dir=ROOT,
        datadir=DATADIR,
        strategy_path=str(ROOT / "freqsrc" / str(item["id"])),
        max_open_trades=2,
        stake_currency="USDT",
        stake_amount=STAKE,
        dry_run_wallet=EQUITY,
        tradable_balance_ratio=0.99,
        dry_run=True,
        fee=FEE,
        runmode=RunMode.BACKTEST,
        trading_mode=TradingMode.FUTURES if is_futures else TradingMode.SPOT,
        margin_mode=margin_mode,
        dataformat_ohlcv="feather",
        cache="none",
        export="none",
        exchange=dict(
            name="binance",
            pair_whitelist=list(pairs),
            pair_blacklist=[],
            enable_ws=False,
        ),
        pairlists=[{"method": "StaticPairList"}],
        internals={"process_throttle_secs": 5},
        entry_pricing={
            "price_side": "same",
            "use_order_book": False,
            "price_last_balance": 0.0,
        },
        exit_pricing={"price_side": "same", "use_order_book": False},
        enable_protections=True,
        unfilledtimeout={
            "entry": 10,
            "exit": 10,
            "exit_timeout_count": 0,
            "unit": "minutes",
        },
    )
    if item["id"] == 5813:
        config["timeframe"] = "5m"
    exchange = native_market(config, is_futures, max_leverage=max_leverage)
    engine = None
    try:
        engine = Backtesting(
            config, exchange=exchange, progress_callback=lambda _: None
        )
        strat = engine.strategylist[0]
        interval = engine.timeframe
        seconds = timeframe_to_seconds(interval)
        start, stop = map(stamp, dates)
        start = math.ceil(start / seconds) * seconds
        stop = (stop // seconds) * seconds
        min_warmup = min(
            400,
            (start - int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()))
            // seconds,
        )
        if (
            engine.required_startup > min_warmup
            and engine.required_startup * seconds
            > start - int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp())
        ):
            raise ValueError(
                "Declared source warmup exceeds the available archive history"
            )
        engine.required_startup = max(engine.required_startup, min_warmup)
        engine.config["startup_candle_count"] = engine.required_startup
        engine.timerange = TimeRange("date", "date", start, stop - 1)
        data, timerange = engine.load_bt_data()
        assert set(data) == set(pairs), "Missing a requested market"
        assert all(
            df.date.iloc[-1].timestamp() == stop - seconds for df in data.values()
        ), "Incomplete market window"
        engine.backtest_one_strategy(strat, data, timerange)
        trades = engine.all_bt_content[name]["results"]
        records = trades.to_dict("records")
        native_trades = {}
        if order_ledger:
            from freqtrade.persistence import LocalTrade

            for trade in LocalTrade.bt_trades:
                key = (trade.pair, trade.open_date_utc, trade.close_date_utc)
                assert key not in native_trades
                native_trades[key] = trade
        groups = {p: [] for p in pairs}
        unsettled = defaultdict(int)
        for row in records:
            pair = row["pair"]
            if row["exit_reason"] == "force_exit":
                unsettled[pair] += 1
                continue
            assert (
                row["open_date"].timestamp() >= start
                and row["close_date"].timestamp() < stop
            ), "Trade outside frozen window"
            side = -1 if row["is_short"] else 1
            if order_ledger:
                trade = native_trades[pair, row["open_date"], row["close_date"]]
                open_value, close_value, benchmark = order_ledger(trade)
            else:
                open_value = row["open_rate"] * row["amount"]
                close_value = row["close_rate"] * row["amount"]
                benchmark = row["profit_abs"]
            gross = side * (close_value - open_value)
            fees = (open_value + close_value) * FEE
            fee_only = gross - fees
            funding_cash = row.get("funding_fees") or 0.0
            assert math.isclose(
                fee_only + funding_cash, benchmark, rel_tol=2e-5, abs_tol=0.001
            ), "Native gross, fees and funding failed trade reconciliation"
            groups[pair].append(
                (
                    int(row["close_date"].timestamp()),
                    gross,
                    fee_only,
                    fee_only + funding_cash - (open_value + close_value) * EXECUTION,
                    funding_cash,
                )
            )
        market_suffix = " perp" if is_futures else ""
        return [
            summary(
                item,
                p.replace(":USDT", "") + market_suffix,
                label,
                interval,
                source_hash,
                groups[p],
                unsettled[p],
            )
            for p in pairs
        ] + [
            summary(
                item,
                "BTC + ETH" + market_suffix,
                label,
                interval,
                source_hash,
                sum(groups.values(), []),
                sum(unsettled.values()),
            )
        ]
    finally:
        if engine:
            engine.cleanup()
        exchange.close()


def main():
    warnings.filterwarnings("ignore")
    label, *target = sys.argv[1:]
    assert label.isalnum()
    logging.basicConfig(
        filename=ROOT / f"freq-{label}.log", level=logging.WARNING, encoding="utf-8"
    )
    if target == ["prepare"]:
        prepare_data()
        return
    if not (ROOT / "freqdata-meta-v2.json").exists():
        prepare_data()
    stock = read(ROOT / "freq-catalogue.json")
    selected = set(map(int, target)) if target else None
    with (ROOT / f"freq-{label}-out.jsonl").open("w", encoding="utf-8") as out:
        for item, name, mode, digest in candidate_sources(stock):
            ident = item["id"]
            if selected and ident not in selected:
                continue
            try:
                if name is None:
                    raise ValueError(
                        "No independently loadable strategy class in this source file"
                    )
                if mode == "complex_futures":
                    raise ValueError(
                        "Source leverage/position adjustment needs archived margin tiers or execution inputs"
                    )
                results = [
                    row
                    for label, dates in WINDOWS.items()
                    for row in analyze(item, name, mode, digest, label, dates)
                ]
                record = dict(id=ident, results=results)
            except Exception as exc:
                logging.exception("Rejected ID %s", ident)
                record = dict(
                    id=ident,
                    reason=f"{type(exc).__name__}: {exc}".splitlines()[0].replace(
                        str(ROOT), "scratch"
                    ),
                )
            out.write(json.dumps(record, allow_nan=False) + "\n")
            out.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        (ROOT / "freq-failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
