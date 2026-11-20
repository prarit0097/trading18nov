"""Audit pinned framework entries and replay the complete timed-order example."""

import argparse
import ast
import hashlib
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_basis import SECOND, snapshots
from research.nonpine_round4_metrics import metrics

IDENT = 5971
SCOPE = "Framework inputs needed"
MONITORS = {5973, 5975, 5976, 5977}
EVALUATORS = {6000, 6001, 6002}
ENTRIES = {5970, 5972}
FEE, BUFFER, ORDER_QUOTE = 0.0005, 0.0003, 100
ORDER_CALLS = {
    "OrderExecutorConfig",
    "PositionExecutorConfig",
    "CreateExecutorAction",
    "create_order",
    "create_new_orders",
    "create_order_instance",
    "buy",
    "sell",
    "cancel_order",
    "submit_trading_evaluation",
}


def blocks(archive, path):
    assert path in archive.namelist(), path
    yield path, archive.read(path)
    if path.endswith("/metadata.json"):
        directory = path.rsplit("/", 1)[0] + "/"
        for name in archive.namelist():
            if (
                name.startswith(directory)
                and name.endswith(".py")
                and "/tests/" not in name
                and not name.endswith("/__init__.py")
            ):
                yield name, archive.read(name)


def syntax_records(name, raw):
    record = {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}
    if not name.endswith(".py"):
        return record
    tree = ast.parse(raw)
    methods = [
        x
        for x in ast.walk(tree)
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    calls = []
    for x in ast.walk(tree):
        if isinstance(x, ast.Call):
            func = x.func
            label = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if label in ORDER_CALLS:
                calls.append([label, x.lineno])
    record["order_call_sites"] = sorted(calls, key=lambda x: x[1])
    record["action_methods"] = [
        {
            "name": x.name,
            "line": x.lineno,
            "returns_empty_list": any(
                isinstance(y, ast.Return)
                and isinstance(y.value, ast.List)
                and not y.value.elts
                for y in ast.walk(x)
            ),
        }
        for x in methods
        if x.name
        in {"determine_executor_actions", "matrix_callback", "create_new_orders"}
    ]
    record["classes"] = [
        [x.name, x.lineno] for x in ast.walk(tree) if isinstance(x, ast.ClassDef)
    ]
    return record


def classify(ident, recs, prior):
    call_sites = [site for r in recs for site in r.get("order_call_sites", [])]
    methods = [m for r in recs for m in r.get("action_methods", [])]
    if ident in MONITORS:
        assert not call_sites and len(methods) == 1 and methods[0]["returns_empty_list"]
        return "Excluded · Monitor without orders", (
            f"Source determine_executor_actions at line {methods[0]['line']} returns an empty list. "
            "This controller only supplies observations or status and defines no executable trade."
        )
    if ident in EVALUATORS:
        assert not call_sites and any(x["name"] == "matrix_callback" for x in methods)
        return "Excluded · Standalone signal component", (
            "Pinned OctoBot evaluator emits an evaluation from the matrix. "
            "Its source does not create an order. A configured trading mode provides entry, sizing and exits."
        )
    if ident in ENTRIES:
        assert [x[0] for x in call_sites] == [
            "OrderExecutorConfig",
            "CreateExecutorAction",
        ]
        assert all(r["path"].endswith(".py") for r in recs)
        return "Excluded · Entry-only example", (
            "The archived example places buy orders only under its default setup and includes no position exit. "
            "A completed-trade P&L would require an additional order rule."
        )
    return prior["status"], prior["reason"]


def timed_roundtrip(updates, start, end):
    quote = None
    started = position = closing_signal = None
    size = 0.0
    for at in range(start - 2, end + 1):
        quote = updates.get(at, quote)
        if at < start or quote is None or at * SECOND - quote[0] >= SECOND:
            continue
        _, bid, ask, size_bid, size_ask = quote
        if started is None:
            started = at
            size = math.floor(1000 * ORDER_QUOTE / ((bid + ask) / 2)) / 1000
        elif position is None:
            if size_ask >= size:
                position = (at, ask)
            else:
                return [], 0, {"entry_signal_at": started, "missing_entry_depth": True}
        elif closing_signal is None and at - started > 10:
            closing_signal = at
        elif closing_signal is not None and size_bid >= size:
            opened, price = position
            turnover = size * (price + bid)
            row = (at, size * (bid - price), turnover * FEE, turnover * BUFFER)
            return (
                [row],
                0,
                {
                    "size": size,
                    "entry_signal_at": started,
                    "entry_at": opened,
                    "exit_signal_at": closing_signal,
                    "exit_at": at,
                    "entry": price,
                    "exit": bid,
                },
            )
    return [], int(position is not None), {"entry_signal_at": started}


def run(hummingbot, octobot, prior_quotes, baseline, output):
    scoped = [r for r in read(baseline)["disposition"] if r["status"] == SCOPE]
    assert len(scoped) == 45
    coverage, sources = [], {}
    with ZipFile(hummingbot) as hb, ZipFile(octobot) as octo:
        for prior in scoped:
            ident = prior["id"]
            url = prior["source"]
            ref, rel = unquote(url.split("/blob/", 1)[1]).split("/", 1)
            repo = "hummingbot" if "/hummingbot/" in url else "OctoBot-Tentacles"
            zipfile = hb if repo == "hummingbot" else octo
            recs = [
                syntax_records(n, raw)
                for n, raw in blocks(zipfile, f"{repo}-{ref}/{rel}")
            ]
            sources[str(ident)] = recs
            status, reason = classify(ident, recs, prior)
            coverage.append([ident, status, reason])

    docs = [
        x
        for x in read(prior_quotes / "manifest.json")
        if x["exchange"] == "binance-futures"
    ]
    results, receipts = [], {}
    for x in docs:
        date, symbol = x["date"], x["symbol"]
        stamp = int(datetime.fromisoformat(date + "T00:00:00+00:00").timestamp())
        start, end = stamp + 300, stamp + 360
        grid = snapshots(prior_quotes / x["file"], x, start, end)
        closed, unresolved, ledger = timed_roundtrip(grid, start, end)
        assert len(closed) == 1 and unresolved == 0, (date, symbol, ledger)
        receipts[f"{date}/{symbol}"] = ledger
        results.append(
            {
                "id": IDENT,
                "period": date,
                "group": "Hummingbot · Timed lifecycle variant",
                "market": symbol + " perp",
                "currency": "USDT",
                "interval": "1s quotes",
                "archive_interval": "Binance USD-M top of book",
                "exit": "Full close after more than 10s",
                **metrics(closed, unresolved),
            }
        )
    assert len(results) == 4
    for row in coverage:
        if row[0] == IDENT:
            row[1:] = [
                "Tested · Timed order execution example",
                (
                    "Pinned example's full market close after a strict 10-second cooldown. "
                    "BTC/ETH Binance USD-M with 100 USDT adapted stake for minimum lot size, "
                    "one start per asset and date, causal quotes and displayed-size checks."
                ),
            ]
    write(
        output,
        {
            "coverage": coverage,
            "source_records": sources,
            "results": results,
            "quote_receipts": docs,
            "timed_fills": receipts,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("hummingbot", "octobot", "prior_quotes", "baseline", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
