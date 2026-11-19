"""Conservative OHLC replay of pending FMZ stop, limit and bracket orders."""

import argparse
import ast
from collections import Counter
from copy import copy
from dataclasses import dataclass
import csv
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

import numpy as np
import talib

from research.delta_fmz_replay import (
    FMZ_REF,
    Series,
    Unsupported,
    expression,
    parse,
    segments,
)
from research.delta_strategy_replay import (
    BAR,
    COINS,
    EXECUTION,
    FEE,
    LATER,
    NOTIONAL,
    REFERENCES,
    ROOT,
    load,
    stamp,
    summarize,
    trading_bar,
)

GROUP = "FMZ stop & limit ports"
EXIT = "Source stop / limit exits"
TICK = {"BTCUSD": 0.1, "ETHUSD": 0.05}
POSITION_FIELDS = {
    "strategy.position_avg_price": "_fmz_avg",
    "strategy.position_size": "_fmz_size",
}


@dataclass(frozen=True)
class PricedOrder:
    source: object
    levels: dict


@dataclass(frozen=True)
class Position:
    identity: str
    direction: int
    price: float

    @property
    def size(self):
        return self.direction * NOTIONAL / self.price


class TickSyntax(ast.NodeTransformer):
    def visit_Attribute(self, node):
        if ast.unparse(node) == "syminfo.mintick":
            return ast.Name(id="_fmz_tick", ctx=ast.Load())
        return node


class PricedSeries(Series):
    def array(self, value):
        return super().array(bool(value) if isinstance(value, np.bool_) else value)


class SnapshotExpressions:
    """Precalculate static series. Bind position-dependent arithmetic at each close."""

    series_type = PricedSeries

    def __init__(self, bars, variables, tick):
        normalized = {
            name: ast.unparse(TickSyntax().visit(expression(text)))
            for name, text in variables.items()
            if self.can_parse(text)
        }
        self.series = self.series_type(bars, normalized)
        self.series.cache["_fmz_tick"] = tick
        self.variables = normalized
        self.scalars = self.series_type(bars[:1], {})
        self.sources = []

    @staticmethod
    def can_parse(text):
        try:
            expression(text)
        except Unsupported:
            return False
        return True

    def expand(self, node, aliases=frozenset()):
        if isinstance(node, ast.Attribute) and ast.unparse(node) in POSITION_FIELDS:
            return ast.Name(id=POSITION_FIELDS[ast.unparse(node)], ctx=ast.Load())
        if isinstance(node, ast.Name) and node.id in self.variables:
            if node.id in aliases:
                raise Unsupported("Recursive series needs a native Pine adapter")
            parsed = expression(self.variables[node.id])
            value = self.expand(parsed, aliases | {node.id})
            return value if self.dynamic(value) else node
        updated = copy(node)
        for key, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                value = self.expand(value, aliases)
            elif isinstance(value, list):
                value = [
                    self.expand(x, aliases) if isinstance(x, ast.AST) else x
                    for x in value
                ]
            setattr(updated, key, value)
        return updated

    @staticmethod
    def dynamic(node):
        return any(
            isinstance(n, ast.Name) and n.id in POSITION_FIELDS.values()
            for n in ast.walk(node)
        )

    def compile(self, node):
        tree = self.expand(TickSyntax().visit(node))
        if not self.dynamic(tree):
            return self.series.array(self.series.evaluate(tree))
        if any(
            isinstance(n, ast.Subscript) and self.dynamic(n) for n in ast.walk(tree)
        ):
            raise Unsupported("Prior position state needs native Pine history")
        return self.replace_static(tree)

    def replace_static(self, node):
        if not self.dynamic(node):
            values = self.series.array(self.series.evaluate(node))
            ident = f"_fmz_static_{len(self.sources)}"
            self.sources.append((ident, values))
            return ast.Name(id=ident, ctx=ast.Load())
        if isinstance(node, ast.Call):
            allowed = {
                "abs",
                "min",
                "max",
                "nz",
                "na",
                "iff",
                "math.abs",
                "math.min",
                "math.max",
            }
            if ast.unparse(node.func) not in allowed:
                raise Unsupported(
                    "Position-dependent indicator needs native Pine state"
                )
            return ast.Call(
                func=node.func,
                args=[self.replace_static(x) for x in node.args],
                keywords=node.keywords,
            )
        if isinstance(node, ast.Name):
            return node
        updated = copy(node)
        for key, value in ast.iter_fields(node):
            if isinstance(value, ast.expr):
                value = self.replace_static(value)
            elif isinstance(value, list):
                value = [
                    self.replace_static(x) if isinstance(x, ast.expr) else x
                    for x in value
                ]
            setattr(updated, key, value)
        return updated

    def at_close(self, index, position):
        self.scalars.cache["_fmz_avg"] = position.price if position else math.nan
        self.scalars.cache["_fmz_size"] = position.size if position else 0.0
        for ident, values in self.sources:
            self.scalars.cache[ident] = values[index]

    def value(self, expr, index):
        if isinstance(expr, np.ndarray):
            return float(expr[index])
        result = self.scalars.evaluate(expr)
        return float(np.asarray(result).item())


def entry_price(order, direction, bar):
    """Return fill price and whether the fill is known to occur at the open."""
    opening = bar["open"]
    if "limit" in order:
        limit = order["limit"]
        if opening <= limit if direction == 1 else opening >= limit:
            return opening, True
        if bar["low"] < limit if direction == 1 else bar["high"] > limit:
            return limit, False
        return None
    if "stop" in order:
        stop = order["stop"]
        if opening >= stop if direction == 1 else opening <= stop:
            return opening, True
        if bar["high"] >= stop if direction == 1 else bar["low"] <= stop:
            return stop, False
        return None
    return opening, True


def bracket_price(levels, position, bar, *, entered_at_open=True, fresh=False):
    direction = position.direction
    opening = bar["open"]
    stop, limit = levels.get("stop"), levels.get("limit")
    if entered_at_open:
        if stop is not None and (
            opening <= stop if direction == 1 else opening >= stop
        ):
            return opening, "protective stop"
        if limit is not None and (
            opening >= limit if direction == 1 else opening <= limit
        ):
            return opening, "protective limit"
    if stop is not None:
        adverse_extreme = bar["low"] if direction == 1 else bar["high"]
        if adverse_extreme <= stop if direction == 1 else adverse_extreme >= stop:
            if fresh and not entered_at_open:
                price = (
                    min(stop, position.price)
                    if direction == 1
                    else max(stop, position.price)
                )
                return price, "protective stop"
            return stop, "protective stop"
    if limit is not None and entered_at_open:
        favorable_extreme = bar["high"] if direction == 1 else bar["low"]
        if favorable_extreme > limit if direction == 1 else favorable_extreme < limit:
            return limit, "protective limit"
    return None


def settlement(position, price, slot):
    size = NOTIONAL / position.price
    gross = position.direction * size * (price - position.price)
    turnover = size * (position.price + price)
    return slot, gross, gross - FEE * turnover, gross - (FEE + EXECUTION) * turnover


class OrderBook:
    def __init__(self, tick, events):
        self.tick = tick
        self.events = events
        self.entries = {}
        self.brackets = {}
        self.closes = set()
        self.position = None
        self.trades = []

    def levels(self, position):
        bracket = self.brackets.get(position.identity)
        if not bracket:
            return {}
        levels = dict(bracket.levels)
        if "loss" in levels and "stop" not in levels:
            levels["stop"] = (
                position.price - position.direction * levels.pop("loss") * self.tick
            )
        if "profit" in levels and "limit" not in levels:
            levels["limit"] = (
                position.price + position.direction * levels.pop("profit") * self.tick
            )
        return levels

    def close(self, price, slot):
        self.trades.append(settlement(self.position, price, slot))
        self.brackets.pop(self.position.identity, None)
        self.position = None

    def advance(self, bar, slot):
        if not trading_bar(bar):
            return
        if self.position and (
            "*" in self.closes or self.position.identity in self.closes
        ):
            self.close(bar["open"], slot)
        # Market orders expire once the first eligible open has been processed.
        self.closes.clear()
        fills = []
        for identity, order in self.entries.items():
            if self.position and order.source.direction == self.position.direction:
                continue
            hit = entry_price(order.levels, order.source.direction, bar)
            if hit is not None:
                fills.append((identity, order, *hit))
        exit_price = None
        if self.position:
            exit_price = bracket_price(self.levels(self.position), self.position, bar)
        if len(fills) > 1 or (fills and exit_price is not None):
            raise Unsupported(
                "Competing entry or reversal and bracket fills need intrabar ordering"
            )
        if exit_price is not None:
            price, kind = exit_price
            self.events[kind] += 1
            self.close(price, slot)
        if fills:
            ident, order, price, at_open = fills[0]
            del self.entries[ident]
            group = order.source.oca_group
            if group:
                for key in tuple(self.entries):
                    if self.entries[key].source.oca_group == group:
                        self.entries.pop(key)
                        self.brackets.pop(key, None)
            if self.position:
                self.close(price, slot)
            self.position = Position(ident, order.source.direction, price)
            kind = (
                "limit entry"
                if "limit" in order.levels
                else "stop entry"
                if "stop" in order.levels
                else "market entry"
            )
            self.events[kind] += 1
            immediate = bracket_price(
                self.levels(self.position),
                self.position,
                bar,
                entered_at_open=at_open,
                fresh=True,
            )
            if immediate is not None:
                price, kind = immediate
                self.events[kind] += 1
                self.close(price, slot)
        self.entries = {k: v for k, v in self.entries.items() if v.levels}

    def submit(self, orders, levels):
        new_entries = filled_close = False
        for order, prices in zip(orders, levels):
            name, kind = order.identity, order.action
            if kind in {"cancel", "cancel_all"}:
                if kind == "cancel_all":
                    self.entries.clear()
                    self.brackets.clear()
                else:
                    self.entries.pop(name, None)
                    if not self.position or self.position.identity != name:
                        self.brackets.pop(name, None)
                    self.brackets = {
                        k: v
                        for k, v in self.brackets.items()
                        if v.source.identity != name
                    }
            elif kind == "entry":
                if self.position and self.position.direction == order.direction:
                    continue
                if order.prices and not prices:
                    continue
                self.entries[name] = PricedOrder(order, prices)
                new_entries = True
            elif kind in {"close", "close_all"}:
                if self.position and (
                    kind == "close_all" or name == self.position.identity
                ):
                    self.closes.add("*" if kind == "close_all" else name)
                    filled_close = True
            elif prices:
                targets = {
                    k
                    for k in self.entries
                    if not order.from_entry or k == order.from_entry
                }
                if self.position and (
                    not order.from_entry or order.from_entry == self.position.identity
                ):
                    targets.add(self.position.identity)
                for target in targets:
                    previous = self.brackets.get(target)
                    if previous and previous.source.identity != name:
                        raise Unsupported(
                            "Multiple simultaneous brackets require exit reservation"
                        )
                    self.brackets[target] = PricedOrder(order, prices)
        if new_entries and filled_close:
            raise Unsupported(
                "Simultaneous entry and manual close require Pine priority"
            )


def replay(program, parts, start, end):
    samples, unresolved = {}, {}
    events = Counter()
    for symbol, groups in parts.items():
        samples[symbol] = []
        unresolved[symbol] = 0
        for times, bars in groups:
            prepared = SnapshotExpressions(bars, program.variables, TICK[symbol])
            signals = [
                (
                    order,
                    [prepared.compile(c) for c in order.conditions],
                    {k: prepared.compile(v) for k, v in order.prices.items()},
                )
                for order in program.orders
            ]
            book = OrderBook(TICK[symbol], events)
            for index, (slot, bar) in enumerate(zip(times, bars)):
                if not start <= slot < end:
                    continue
                book.advance(bar, slot)
                prepared.at_close(index, book.position)
                orders, prices = [], []
                for order, conditions, levels in signals:
                    values = [prepared.value(x, index) for x in conditions]
                    if not all(math.isfinite(x) and x != 0 for x in values):
                        continue
                    resolved = {
                        k: prepared.value(expr, index) for k, expr in levels.items()
                    }
                    resolved = {k: v for k, v in resolved.items() if math.isfinite(v)}
                    if any(v <= 0 for v in resolved.values()):
                        raise Unsupported(
                            "Non-positive price or tick distance in order"
                        )
                    if order.action == "entry" and levels and not resolved:
                        continue
                    orders.append(order)
                    prices.append(resolved)
                book.submit(orders, prices)
            samples[symbol].extend(book.trades)
            unresolved[symbol] += int(book.position is not None)
    samples["BTC + ETH"] = samples["BTCUSD"] + samples["ETHUSD"]
    unresolved["BTC + ETH"] = unresolved["BTCUSD"] + unresolved["ETHUSD"]
    return samples, unresolved, dict(events)


def run(archive, reference, later):
    manifest = json.loads(REFERENCES.read_bytes())
    earlier = json.loads((ROOT / "delta-fmz-replay.json").read_bytes())
    pending = {
        i for i, status, _ in earlier["coverage"] if not status.startswith("Tested")
    }
    windows = {}
    for label, begin, end, path in [
        (
            "Reference",
            manifest["from_ist"][:10],
            manifest["to_ist_exclusive"][:10],
            reference,
        ),
        ("Later", *LATER, later),
    ]:
        candles, hashes = load(path)
        assert hashes == earlier["candle_sha256"][label]
        first, last = stamp(begin), stamp(end)
        windows[label] = (segments(candles, first, last), first, last, hashes)
    coverage, results = [], []
    np.seterr(all="ignore")
    guide = r"(?m)^\s*strategy\.(?:entry|exit)\s*\([^\n]*"
    price_keyword = r"\b(?:stop|limit|loss|profit)\s*="
    with (
        ZipFile(archive) as z,
        (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream,
    ):
        for idx, row in enumerate(csv.DictReader(stream), 1):
            if idx not in pending:
                continue
            filename = unquote(row["source_url"].split("/" + FMZ_REF + "/")[-1])
            raw = z.read("strategies-" + FMZ_REF + "/" + filename)
            blocks = re.findall(
                r"(?ms)^\x60{3}[^\n]*\n(.*?)^\x60{3}", raw.decode("utf8")
            )
            codes = [
                b
                for b in blocks
                if re.search(r"\bstrategy\s*\(", b)
                and any(re.search(price_keyword, line) for line in re.findall(guide, b))
            ]
            if not codes:
                continue
            try:
                if len(codes) != 1:
                    raise Unsupported("Multiple priced Pine scripts in archive entry")
                code = codes[0]
                interval = re.search(r"(?m)^\s*period\s*:\s*(\S+)\s*$", code)
                label = interval[1] if interval else ""
                strategy = parse(code, label, priced_orders=True)
                if not any(order.prices for order in strategy.orders):
                    raise Unsupported("No reachable priced order declarations")
                simulated = []
                for period, (parts, first, last, _) in windows.items():
                    samples, missing, events = replay(strategy, parts, first, last)
                    for market, sample in samples.items():
                        item = summarize(
                            (GROUP, row["name"], market, EXIT),
                            period,
                            sample,
                            missing[market],
                        )
                        item.update(
                            id=idx,
                            source=row["source_url"],
                            archive_interval=label,
                            source_sha256=hashlib.sha256(raw).hexdigest(),
                            events=events,
                        )
                        simulated.append(item)
            except Unsupported as exc:
                coverage.append([idx, "FMZ priced order pending", str(exc)])
                continue
            except (ValueError, IndexError, TypeError, ArithmeticError) as exc:
                coverage.append(
                    [
                        idx,
                        "FMZ priced order pending",
                        f"Unsupported priced input ({type(exc).__name__})",
                    ]
                )
                continue
            results.extend(simulated)
            status = (
                "Tested · FMZ priced order"
                if any(t["trades"] for t in simulated)
                else "Tested · FMZ priced, no closes"
            )
            coverage.append(
                [
                    idx,
                    status,
                    "5m stop, limit or bracket order replay with conservative OHLC fills",
                ]
            )
    return {
        "results": results,
        "coverage": coverage,
        "pinned_fmz_ref": FMZ_REF,
        "candle_sha256": {k: v[3] for k, v in windows.items()},
        "delta_tick_size": TICK,
        "libraries": {"talib": talib.__version__, "numpy": np.__version__},
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "reference", "later", "output"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    report = run(args.archive, args.reference, args.later)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf8",
        newline="\n",
    )
    print(Counter(s[1] for s in report["coverage"]))
