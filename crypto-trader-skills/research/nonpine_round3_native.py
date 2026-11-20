"""Replay remaining Freqtrade/Jesse candidates using prior isolated engine inputs."""

import argparse
import ast
import hashlib
import importlib.util
import json
import logging
import math
import sys
import types
from pathlib import Path
from zipfile import ZipFile

LOGGER = logging.getLogger(__name__)

FREQ = {
    5808: "Runs the pinned Almgren–Chriss entry, exit and slice callbacks in native Freqtrade. Candle-level fills with fixed slippage; no market-impact estimate.",
    5829: "Runs the pinned TWAP entry, exit and time-slice callbacks in native Freqtrade. Candle-level fills with fixed slippage; no order queue.",
    5875: "Keep the original signals with ETH/BTC spot reference candles. Remove an unused import and normalize the class header for the Freqtrade resolver.",
    5863: "Remove the unused legacy NumPy import, use an explicit DataFrame assignment for the recursive OTT series, and store floating short-stop values. Retain source timeframe and parameters.",
    5868: "Source Volatility System callbacks and 2x leverage using one modeled isolated maintenance tier at 0.5%. Includes reconciled native fills and historical funding.",
}
JESSE = {
    5944: "Isolated 3x modeled margin, source Turtle rules and sizing. No funding or execution queue."
}
PARTIAL_FILLS = {5808, 5829, 5868}


def normalize_multi_tf(code):
    source, target = "class multi_tf (", "class multi_tf("
    if code.count(source) != 1:
        raise ValueError("Expected exactly one spaced class header")
    changed = code.replace(source, target)
    assert ast.dump(ast.parse(code)) == ast.dump(ast.parse(changed))
    return changed


def reconstructed_turnover(fills):
    exposure = opened = closed = 0.0
    for fill in fills:
        qty, price = fill["amount"], fill["price"]
        if not (math.isfinite(qty) and math.isfinite(price) and qty > 0 and price > 0):
            raise ValueError("Invalid native order fill")
        if fill["entry"]:
            opened += qty * price
            exposure += qty
        else:
            closed += qty * price
            exposure -= qty
        if exposure < -1e-8:
            raise ValueError("Native exit exceeds entry quantity")
    if abs(exposure) > 1e-8 or not (opened and closed):
        raise ValueError("Closed native trade has unmatched order quantities")
    return opened, closed


def native_order_ledger(trade):
    fills = [
        {
            "amount": order.safe_amount_after_fee,
            "price": order.safe_price,
            "entry": order.ft_order_side == trade.entry_side,
        }
        for order in trade.orders
        if not order.ft_is_open and order.safe_filled > 0
    ]
    opened, closed = reconstructed_turnover(fills)
    split_exit = sum(not order["entry"] for order in fills) > 1
    benchmark = trade.realized_profit if split_exit else trade.close_profit_abs
    return opened, closed, benchmark


def import_file(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def freqtrade(root, ident):
    base = import_file("nonpine_freqtrade", root / "nonpine_freqtrade.py")
    prior = import_file(
        "nonpine_round2_freqtrade", root / "nonpine_round2_freqtrade.py"
    )
    guard = prior.ReplayGuard()
    logger = logging.getLogger()
    logger.addHandler(guard)
    if ident == 5875:
        prior.informative_ethbtc()
    if ident in (5808, 5829):
        base.EXECUTION_REQUIRED = base.EXECUTION_REQUIRED - {ident}
    stock = base.read(root / "freq-catalogue.json")
    [entry] = list(base.candidate_sources(x for x in stock if x["id"] == ident))
    item, name, mode, digest = entry
    if ident in PARTIAL_FILLS:
        assert mode == "complex_futures"
        mode = "futures"
    [source] = (root / "freqsrc" / str(ident)).glob("*.py")
    changed = (
        prior.repair(ident, source)
        if ident in prior.REPAIRS
        else source.read_text(encoding="utf-8-sig")
    )
    if ident == 5875:
        changed = normalize_multi_tf(changed)
    if ident == 5863:
        changed = prior.once(
            changed,
            'df["Var"].iat[i] =',
            'df.iat[i, df.columns.get_loc("Var")] =',
        )
        changed = prior.once(
            changed,
            'df["shortstop"] = 999999999999999999',
            'df["shortstop"] = 999999999999999999.0',
        )
    source.write_text(changed, encoding="utf-8", newline="\n")
    rows = [
        row
        for label, dates in base.WINDOWS.items()
        for row in base.analyze(
            item,
            name,
            mode,
            digest,
            label,
            dates,
            order_ledger=native_order_ledger if ident in PARTIAL_FILLS else None,
            max_leverage=2 if ident == 5868 else 1,
        )
    ]
    if guard.issue:
        raise ValueError(guard.issue)
    for row in rows:
        row.update(
            group=(
                "Freqtrade · 2x margin variant"
                if ident == 5868
                else "Freqtrade compatibility replay · Binance"
            ),
            repairs=FREQ[ident],
            migrated_sha256=hashlib.sha256(changed.encode()).hexdigest(),
        )
    return rows


def jesse(root, ident):
    base = import_file("nonpine_jesse", root / "nonpine_jesse.py")
    package = types.ModuleType("jesse.research")
    package.__path__ = [str(root / "jesse-deps/jesse/research")]
    sys.modules["jesse.research"] = package
    engine = import_file(
        "isolated_jesse_round3", root / "jesse-deps/jesse/research/backtest.py"
    )
    name, tf, kind, anchor = base.CASES[ident]
    with ZipFile(root / "example.zip") as archive:
        revision = "7c91e0a37bf62165790120d730442e4f6eb00364"
        entry = f"example-strategies-{revision}/{name}/__init__.py"
        source = archive.read(entry)
    digest = hashlib.sha256(source).hexdigest()
    staged = root / "jesse_sources" / f"{name}.py"
    staged.write_bytes(source)
    clss = getattr(import_file(name, staged), name)

    def with_margin(config, *args, **kwargs):
        return engine.backtest(dict(config, futures_leverage=3), *args, **kwargs)

    rows = []
    for label, dates in base.W.items():
        btc, bopen = base.run(with_margin, clss, tf, kind, anchor, dates, "BTC")
        eth, eopen = base.run(with_margin, clss, tf, kind, anchor, dates, "ETH")
        markets = [
            ("BTC", btc, bopen),
            ("ETH", eth, eopen),
            ("BTC + ETH", btc + eth, bopen + eopen),
        ]
        for coin, closed, unsettled in markets:
            row = base.report(
                ident, name, coin, label, tf, kind, digest, closed, unsettled
            )
            row.update(group="Jesse · 3x margin variant", repairs=JESSE[ident])
            rows.append(row)
    return rows


def main(root, ident):
    is_freq = ident in FREQ
    settings = FREQ if is_freq else JESSE
    engine = (
        "Freqtrade 2x margin variant"
        if ident == 5868
        else "Freqtrade compatibility"
        if is_freq
        else "Jesse 3x margin variant"
    )
    logging.basicConfig(
        filename=root / f"round3-native-{ident}.log",
        encoding="utf-8",
        level=logging.INFO,
    )
    sys.path.insert(0, str(root))
    try:
        rows = (freqtrade if is_freq else jesse)(root, ident)
        assert len(rows) == 6 and len({(r["period"], r["market"]) for r in rows}) == 6
        status = "Tested · " + engine
        if not any(r["trades"] for r in rows):
            status += ", no closes"
        reason = settings[ident]
    except Exception as exc:
        LOGGER.exception("Candidate %d did not produce a verified ledger", ident)
        rows = []
        status = engine + " pending"
        message = str(exc).splitlines()[0].replace(str(root), "replay scratch")
        reason = f"{type(exc).__name__}: {message}"
    payload = {"engine": engine, "coverage": [[ident, status, reason]], "results": rows}
    (root / f"round3-native-{ident}.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id", type=int, choices=sorted(FREQ.keys() | JESSE.keys()))
    main(Path(__file__).resolve().parent, parser.parse_args().id)
