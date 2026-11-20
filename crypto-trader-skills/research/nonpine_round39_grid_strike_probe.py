"""Execute pinned Grid Strike CLI using a captured-data-only offline boundary.

Copy this file under r46-grid-strike/ in the offline AppContainer root.
Supply source/ files with prefix 3351ada- using SOURCE_PATHS at REV and
binance/ market archives plus an official checksum manifest. The named
Pandas and Pydantic dependencies go in deps/ under that same isolated root.
The production CLI, engine, controller, config and grid simulator are intact.
Unused exchanges and executor types fail closed. No disk or network API is
available to the publisher's connector provider because it is not imported.
"""

import ast
import asyncio
import csv
import io
import json
import logging
import random
import socket
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Literal
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deps"))
import pandas as pd
import pydantic
from pydantic import BaseModel

REV = "3351adad0a09f6a57a202219d3e52fe794672421"
REL = "91ff6bfa3c4b0c97f0d4f34eb635ef6f5b772db0"
SOURCE = ROOT / "r46-grid-strike" / "source"
RECEIPT = ROOT / "r46-grid-strike" / "runtime-receipt.json"
FILES = {}
EXPECTED_HASHES = {
    "backtest_grid_strike": "7e94e7c71efeab0cf77c39e71470e2273d520d22b23ebfb16720d6b088b3822e",
    "backtesting_data_provider": "e1060d4bc0d32621aa7d58f87f37a649a609fe7dff9ed997bc4038533b9478e7",
    "backtesting_engine_base": "850265b79f666c0df3e66ed4677b7156d81c413813b4559c8b526260abcfa308",
    "backtesting_result": "66ab7a7b87ffb824957822436c7398e0021bf308d63660da2c3b654ceddb80a4",
    "candles_data": "985838f3c7d07d5cf62c83469284c8179ae60c0efc074dd3a0e929639a74243d",
    "common": "b06a787e9ca30d07d9a319a1daa8bcdced727d5be84cacef32893c76e07b680b",
    "config_data_types": "30021373812e03931b936f94492273285e562e52c8834c2448e240e154f8e4e0",
    "controller_base": "1ea9e474c8495373bba65ca8e1918e506a512548c6fd58ca5a2d3081e69b7ee2",
    "distributions": "89ea79975024c0e087e97c01f812babf17ff6992b55d2604b5122774cb29f03f",
    "executor_actions": "e984fd71c5ce0abd0f010938ccf8a682cefa52e2cc1270fe740f88075e068936",
    "executor_data": "9f9c60a70e25e7dee4288bbfcef43a228ffe7e2ae544fd19943e5df4b09a3b1a",
    "executor_simulator_base": "cd175711b3d24398430e85cd328606aebb9785c5c6b834c9bc142a87afa82c94",
    "executors_info": "58cd3d600fc9cf4922e0a16b526014f87ba3ca7f43d2c131cc42e0df968fc64a",
    "grid_data": "2be2c43f6bfb8693fe7888db363379b77d7d7dce3861b1ecaf4810794c3ff9bd",
    "grid_executor_simulator": "05e917c3c1d8770959864b2d04e483c53946111411c890fc6653cb834609d211",
    "grid_strike": "65878e0f648b258c644112bdd0c07fe3687fb9b3654fda6aa85f796fd05698bc",
    "model_base": "bec9767f714a2ee09dd74e4b3137fef88bfeba3fef6582ef896ea48504ed8c98",
    "model_executors": "bb567313b858df2f908f7570199ff661b3f353d51fa6692ec40476ddeda584d6",
    "order_data": "ff62fbd7c774754ba872d9692129f06e473821638277d850d80480f1cd67b409",
    "position_config": "998116b41eb6504677e1cedcfa7625b3778f608d1868cf9a0b255b46c57ffd5e",
    "position_data": "54f4b904726db51de8ce7e0221f4c09e46b780aeb0b1dac15f7465fa246a563f",
    "runnable_base": "4d9b396ab787e3ff57b2d90b56aedfc562bb799635d8e51e6b2741373c099b7c",
    "utils_common": "878e6598793af9406ee6817c6950d1fbed0b2fd59aef1f44a04e3a8f45d81b00",
    "validation": "31ca6612070fdd46816625a93458e1a5e11709ce5a47c7f289f1bcc19999e09b",
}
SOURCE_PATHS = {
    "backtest_grid_strike": "scripts/backtest_grid_strike.py",
    "backtesting_data_provider": "hummingbot/strategy_v2/backtesting/backtesting_data_provider.py",
    "backtesting_engine_base": "hummingbot/strategy_v2/backtesting/backtesting_engine_base.py",
    "backtesting_result": "hummingbot/strategy_v2/backtesting/backtesting_result.py",
    "candles_data": "hummingbot/data_feed/candles_feed/data_types.py",
    "common": "hummingbot/core/data_type/common.py",
    "config_data_types": "hummingbot/client/config/config_data_types.py",
    "controller_base": "hummingbot/strategy_v2/controllers/controller_base.py",
    "distributions": "hummingbot/strategy_v2/utils/distributions.py",
    "executor_actions": "hummingbot/strategy_v2/models/executor_actions.py",
    "executor_data": "hummingbot/strategy_v2/executors/data_types.py",
    "executor_simulator_base": "hummingbot/strategy_v2/backtesting/executor_simulator_base.py",
    "executors_info": "hummingbot/strategy_v2/models/executors_info.py",
    "grid_data": "hummingbot/strategy_v2/executors/grid_executor/data_types.py",
    "grid_executor_simulator": "hummingbot/strategy_v2/backtesting/executors_simulator/grid_executor_simulator.py",
    "grid_strike": "controllers/generic/grid_strike.py",
    "model_base": "hummingbot/strategy_v2/models/base.py",
    "model_executors": "hummingbot/strategy_v2/models/executors.py",
    "order_data": "hummingbot/strategy_v2/executors/order_executor/data_types.py",
    "position_config": "hummingbot/strategy_v2/models/position_config.py",
    "position_data": "hummingbot/strategy_v2/executors/position_executor/data_types.py",
    "runnable_base": "hummingbot/strategy_v2/runnable_base.py",
    "utils_common": "hummingbot/strategy_v2/utils/common.py",
    "validation": "hummingbot/strategy_v2/executors/validation.py",
}
MARKET_HASHES = {
    "BTC": "166e586106dda5083a32dbcf68108a80465bea04a60ba05ca3327fab7768a208",
    "ETH": "2a00c3a92769a164d7ecffeffca895bd5d3a06c8ff7059ff6bca0c3ad12e66d8",
}


def denied(*args, **kwargs):
    raise AssertionError("Offline adapter reached an unsupported runtime path")


def module(name, **attrs):
    if "." in name:
        parent, child = name.rsplit(".", 1)
        if parent not in sys.modules:
            module(parent).__path__ = []
    result = ModuleType(name)
    result.__dict__.update(attrs)
    sys.modules[name] = result
    if "." in name:
        setattr(sys.modules[parent], child, result)
    return result


def upstream(name, key, members=None):
    path = SOURCE / f"3351ada-{key}.py"
    raw = path.read_bytes()
    FILES[path.name] = sha256(raw).hexdigest()
    assert FILES[path.name] == EXPECTED_HASHES[key], path
    result = module(name, __file__=str(path))
    if members is not None:
        tree = ast.parse(raw, filename=str(path))
        found = set()
        for node in tree.body:
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "BacktestingDataProvider"
            ):
                node.bases = []
                node.body[:] = [
                    n for n in node.body if getattr(n, "name", None) in members
                ]
                found.update(n.name for n in node.body)
        if found != members:
            raise AssertionError(found ^ members)
        tree.body[:] = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        result.__dict__.update(pd=pd, Decimal=Decimal, PriceType=object)
        raw = tree
    exec(compile(raw, str(path), "exec"), result.__dict__)  # noqa: S102 - pinned source inside AppContainer
    return result


def seed_base58(raw):
    symbols = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    value = int.from_bytes(raw, "big")
    result = bytearray()
    while value:
        value, index = divmod(value, 58)
        result.append(symbols[index])
    zeros = len(raw) - len(raw.lstrip(b"\0"))
    return b"1" * zeros + bytes(reversed(result))


class UnusedConfig(BaseModel):
    unsupported: str

    def model_post_init(self, _context):
        denied()


class UnusedSimulator:
    simulate = staticmethod(denied)


def bind_sources():
    core = "hummingbot.core"
    client = "hummingbot.client"
    v2 = "hummingbot.strategy_v2"
    models, exe = f"{v2}.models", f"{v2}.executors"
    back = f"{v2}.backtesting"
    module("yaml", safe_load=denied)
    module("base58", b58encode=seed_base58)
    module("hummingbot.exceptions", InvalidController=RuntimeError)
    module("hummingbot.logger", HummingbotLogger=logging.Logger)
    module(
        f"{client}.settings",
        CONTROLLERS_MODULE="controllers",
        CONTROLLERS_CONF_DIR_PATH="",
        AllConnectorSettings=SimpleNamespace(),
    )
    module(f"{client}.config.config_validators", validate_connector=denied)
    module(f"{core}.data_type.in_flight_order", InFlightOrder=object)
    module(f"{core}.utils.async_utils", safe_ensure_future=denied)
    module("hummingbot.connector.utils", split_hb_trading_pair=denied)
    module("hummingbot.data_feed.market_data_provider", MarketDataProvider=object)
    upstream(f"{core}.data_type.common", "common")
    upstream(f"{client}.config.config_data_types", "config_data_types")
    upstream("hummingbot.data_feed.candles_feed.data_types", "candles_data")
    upstream(f"{models}.base", "model_base")
    upstream(f"{models}.executors", "model_executors")
    upstream(f"{v2}.utils.common", "utils_common")
    upstream(f"{models}.position_config", "position_config")
    upstream(f"{v2}.runnable_base", "runnable_base")
    upstream(f"{exe}.data_types", "executor_data")
    upstream(f"{exe}.validation", "validation")
    upstream(f"{exe}.position_executor.data_types", "position_data")
    upstream(f"{exe}.grid_executor.data_types", "grid_data")
    upstream(f"{exe}.order_executor.data_types", "order_data")
    for family in ("Arbitrage", "DCA", "LP", "TWAP", "XEMM"):
        # Pydantic tries these union alternatives only if a non-grid config is supplied.
        placeholder = type(
            f"{family}ExecutorConfig",
            (UnusedConfig,),
            {"__annotations__": {"type": Literal[f"{family.lower()}_executor"]}},
        )
        module(
            f"{exe}.{family.lower()}_executor.data_types",
            **{placeholder.__name__: placeholder},
        )
    upstream(f"{models}.executor_actions", "executor_actions")
    upstream(f"{models}.executors_info", "executors_info")
    base = upstream(f"{v2}.controllers.controller_base", "controller_base")
    controllers = sys.modules[f"{v2}.controllers"]
    controllers.ControllerBase = base.ControllerBase
    controllers.ControllerConfigBase = base.ControllerConfigBase
    for name, cls in (
        ("directional_trading", "DirectionalTrading"),
        ("market_making", "MarketMaking"),
    ):
        module(
            f"{v2}.controllers.{name}_controller_base",
            **{f"{cls}ControllerConfigBase": UnusedConfig},
        )
    upstream("controllers.generic.grid_strike", "grid_strike")
    upstream(f"{v2}.utils.distributions", "distributions")
    upstream(f"{back}.executor_simulator_base", "executor_simulator_base")
    upstream(
        f"{back}.executors_simulator.grid_executor_simulator", "grid_executor_simulator"
    )
    for family in ("DCA", "Order", "Position"):
        module(
            f"{back}.executors_simulator.{family.lower()}_executor_simulator",
            **{f"{family}ExecutorSimulator": UnusedSimulator},
        )
    data = upstream(
        f"{back}.backtesting_data_provider",
        "backtesting_data_provider",
        {
            "get_candles_df",
            "get_price_by_type",
            "time",
            "update_backtesting_time",
            "ensure_epoch_index",
        },
    )
    orig_provider = data.BacktestingDataProvider

    class OfflineProvider(orig_provider):
        bars = None

        def __init__(self, connectors):
            assert not connectors
            self.prices = {}
            self.candles_feeds = {}

        def initialize_rate_sources(self, pairs):
            assert all(obj.connector_name == "binance" for obj in pairs)

        async def initialize_trading_rules(self, connector_name):
            assert connector_name == "binance"

        def get_trading_rules(self, connector_name, trading_pair):
            assert connector_name == "binance"
            raise KeyError(trading_pair)  # Official no-metadata fallback.

        async def initialize_candles_feed(self, config):
            assert (config.connector, config.interval) == ("binance", "1m")
            self.candles_feeds[f"binance_{config.trading_pair}_1m"] = self.bars.copy()

    data.BacktestingDataProvider = OfflineProvider
    eng = upstream(f"{back}.backtesting_engine_base", "backtesting_engine_base")
    upstream(f"{back}.backtesting_result", "backtesting_result")
    cli = upstream("published_grid_strike_cli", "backtest_grid_strike")
    return cli, eng.BacktestingEngineBase, OfflineProvider


def source_frame(coin, start, end):
    key = f"klines-spot-{coin}USDT-1m-2026-11-01.zip"
    root = ROOT / "binance"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    item = manifest[key]
    data = (root / key).read_bytes()
    assert sha256(data).hexdigest() == item["sha256_or_error"] == MARKET_HASHES[coin]
    assert item["url"] == (
        f"https://data.binance.vision/data/spot/daily/klines/{coin}USDT/1m/{coin}USDT-1m-2026-11-01.zip"
    )
    with ZipFile(io.BytesIO(data)) as archive:
        [name] = archive.namelist()
        records = list(csv.reader(io.StringIO(archive.read(name).decode())))
    assert len(records) == 1440
    bars = []
    for i, row in enumerate(records):
        now = int(row[0]) // 1_000_000
        assert now == start + i * 60 < end
        assert int(row[6]) + 1 == (now + 60) * 1_000_000
        o, h, l, c, v = map(float, row[1:6])
        assert l <= min(o, c) <= max(o, c) <= h and v >= 0
        bars.append((now, o, h, l, c, v))
    return pd.DataFrame(
        bars, columns=["timestamp", "open", "high", "low", "close", "volume"]
    ), item


def measured(result, provider, overrides):
    by_timestamp = provider.bars.set_index("timestamp")
    totals = {
        "executors": 0,
        "entries": 0,
        "initial_entries": 0,
        "price_outside_candle": 0,
        "take_profits": 0,
        "marked_lots": 0,
        "terminal_gross": 0.0,
        "terminal_fees": 0.0,
        "terminal_net": 0.0,
    }
    events = []
    witness = None
    for executor in result["executors"]:
        start = int(executor.timestamp)
        end = int(executor.close_timestamp)
        history = executor.custom_info["fill_events"]
        price = float(by_timestamp.at[end, "close"])
        opened = {}
        gross = 0.0
        sides = 0
        fees = 0.0
        totals["executors"] += 1
        for event in history:
            now, level, rate, amount = (
                int(event["timestamp"]),
                event["level_idx"],
                event["price"],
                event["amount_quote"],
            )
            assert start <= now <= end
            if event["side"] == "entry":
                assert level not in opened
                assert by_timestamp.at[now, "low"] <= rate
                above_high = bool(rate > by_timestamp.at[now, "high"])
                totals["price_outside_candle"] += above_high
                if witness is None and above_high and now == start:
                    prices = [
                        float(by_timestamp.at[now, field])
                        for field in ("open", "high", "low", "close")
                    ]
                    witness = {
                        "timestamp": now,
                        "ohlc": prices,
                        "simulated_buy": rate,
                        "known_close": now + 60,
                    }
                totals["entries"] += 1
                totals["initial_entries"] += now == start
                opened[level] = now, rate, amount
            else:
                prior, entry, stake = opened.pop(level)
                assert (
                    prior < now
                    and amount == stake
                    and by_timestamp.at[now, "high"] >= rate
                )
                gross += (rate - entry) * stake / entry
                fees += 0.0004 * stake
                sides += 1
        for _, entry, stake in opened.values():
            gross += (price - entry) * stake / entry
            fees += 0.0004 * stake
        assert abs(gross - fees - float(executor.net_pnl_quote)) < 1e-8
        assert abs(fees - float(executor.cum_fees_quote)) < 1e-8
        totals["take_profits"] += sides
        totals["marked_lots"] += len(opened)
        totals["terminal_gross"] += gross
        totals["terminal_fees"] += fees
        totals["terminal_net"] += gross - fees
        events.append([start, end, executor.close_type.name, history])
    assert (
        abs(totals["terminal_net"] - float(result["results"]["net_pnl_quote"])) < 1e-8
    )
    curve = [
        [int(row["timestamp"]), row["total_pnl"]] for row in result["pnl_timeseries"]
    ]
    totals["events_sha256"] = sha256(
        json.dumps(events, sort_keys=True).encode()
    ).hexdigest()
    totals["curve_sha256"] = sha256(json.dumps(curve).encode()).hexdigest()
    totals["first_executor_sample"] = [*events[0][:3], events[0][3][:5]]
    totals["first_launch_bar_execution_above_high"] = witness
    totals["config_changes"] = overrides
    return totals


async def cli_run(cli, engine, provider, bars, coin, start, end, overrides=None):
    provider.bars = bars
    original = engine.run_backtesting
    overrides = overrides or {}
    capture = {}

    async def run(self, config, *args, **kwargs):
        assert kwargs == {"backtesting_resolution": "1m", "trade_cost": 0.0002}
        for key, value in overrides.items():
            setattr(config, key, value)
        result = await original(self, config, *args, **kwargs)
        capture.update(measured(result, provider, overrides))
        return result

    engine.run_backtesting = run
    random.seed(5978)
    cli.time = SimpleNamespace(time=lambda: end, perf_counter=time.perf_counter)
    try:
        await cli.main(
            (end - start) / 86400,
            False,
            None,
            "binance",
            f"{coin}-USDT",
            1000,
            "1m",
            None,
            None,
            None,
            "BUY",
            0.001,
            2,
            20,
            0.04,
        )
    finally:
        engine.run_backtesting = original
    return capture


async def main():
    socket_blocked = False
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=1):
            pass
    except PermissionError:
        socket_blocked = True
    assert socket_blocked, "Expected no network AppContainer access"
    cli, engine, provider = bind_sources()
    start, end = 1793491200, 1793577600  # 2026-11-01 UTC.
    results = {}
    for coin in ("BTC", "ETH"):
        bars, data = source_frame(coin, start, end)
        baseline = await cli_run(cli, engine, provider, bars, coin, start, end)
        hard = await cli_run(
            cli,
            engine,
            provider,
            bars,
            coin,
            start,
            end,
            {
                "max_open_orders": 1,
                "max_orders_per_batch": 7,
                "order_frequency": 1800,
                "activation_bounds": Decimal("0.00001"),
                "leverage": 1,
            },
        )
        assert baseline["initial_entries"] > 2, baseline
        assert baseline["events_sha256"] == hard["events_sha256"]
        assert baseline["curve_sha256"] == hard["curve_sha256"]
        results[coin] = {
            "source_data": data,
            "baseline": baseline,
            "constraint_sensitivity": hard,
        }
    receipt = {
        "source_sha256": FILES,
        "source_paths": SOURCE_PATHS,
        "catalogue_revision": REV,
        "v2_14_release_revision": REL,
        "engine_scope": "pinned native CLI main, controller, engine and Grid simulator",
        "runtime": {
            "python": sys.version.split()[0],
            "pandas": pd.__version__,
            "pydantic": pydantic.__version__,
        },
        "network_denied": socket_blocked,
        "market": results,
    }
    RECEIPT.write_text(
        json.dumps(receipt, default=str, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    import traceback

    with (
        (RECEIPT.parent / "run.log").open("w", encoding="utf-8") as log,
        redirect_stdout(log),
        redirect_stderr(log),
    ):
        try:
            asyncio.run(main())
        except Exception:
            traceback.print_exc()
            raise
