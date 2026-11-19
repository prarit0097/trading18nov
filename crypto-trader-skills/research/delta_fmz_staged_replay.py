"""Replay pending FMZ partial exits and stop-limit orders on public Delta bars."""

import argparse
import ast
import csv
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

import numpy as np
import talib

from research.delta_fmz_priced_replay import (
    TICK,
    Position,
    PricedOrder,
    PricedSeries,
    SnapshotExpressions,
    bracket_price,
    entry_price,
    settlement,
)
from research.delta_fmz_replay import (
    FMZ_REF,
    Unsupported,
    expression,
    parse,
    segments,
    source_lines,
)
from research.delta_strategy_replay import (
    EXECUTION,
    FEE,
    LATER,
    NOTIONAL,
    REFERENCES,
    ROOT,
    drawdown,
    load,
    stamp,
    summarize,
    trading_bar,
)

GROUP = "FMZ partial & stop-limit"
EXIT = "Source partial / staged"
EPSILON = 1e-10
COST_KEYS = ("gross", "after_fees", "net")


def features(lines):
    partial = staged = False
    for _, line in lines:
        if re.match(r"strategy\.(?:exit|close)\s*\(", line):
            percent = re.search(r"\bqty_percent\s*=\s*([^,)]+)", line)
            if re.search(r"\bqty\s*=", line) or (
                percent and not re.fullmatch(r"100(?:\.0+)?", percent[1].strip())
            ):
                partial = True
        if (
            re.match(r"strategy\.(?:entry|order)\s*\(", line)
            and re.search(r"\bstop\s*=", line)
            and re.search(r"\blimit\s*=", line)
        ):
            staged = True
    return partial, staged


def full_size_default(node, variables, visited=frozenset()):
    if isinstance(node, ast.Constant):
        return node.value == 100
    if isinstance(node, ast.Name) and node.id in variables and node.id not in visited:
        return full_size_default(
            expression(variables[node.id]), variables, visited | {node.id}
        )
    if isinstance(node, ast.Call) and ast.unparse(node.func) in {
        "input",
        "input.int",
        "input.float",
    }:
        default = next(
            (k.value for k in node.keywords if k.arg == "defval"),
            node.args[0] if node.args else None,
        )
        return full_size_default(default, variables, visited)
    return False


class StagedSeries(PricedSeries):
    def function(self, node):
        name = ast.unparse(node.func)
        name = name.removeprefix("ta.")
        if name in {"valuewhen", "barssince", "stoch", "sar"} and not node.keywords:
            args = [self.evaluate(arg) for arg in node.args]
            if name == "valuewhen" and len(args) == 3:
                trigger = self.truth(args[0])
                occurrence = self.scalar_int(args[2])
                indices = np.flatnonzero(trigger)
                positions = np.cumsum(trigger) - occurrence - 1
                valid = positions >= 0
                values = np.full(self.size, np.nan)
                values[valid] = self.array(args[1])[indices[positions[valid]]]
                return values
            if name == "barssince" and len(args) == 1:
                indexes = np.arange(self.size)
                latest = np.maximum.accumulate(
                    np.where(self.truth(args[0]), indexes, -1)
                )
                return np.where(latest >= 0, indexes - latest, np.nan)
            if name == "stoch" and len(args) == 4:
                source, high, low = map(self.array, args[:3])
                length = self.scalar_int(args[3])
                if length < 2:
                    raise Unsupported("Unsupported stochastic lookback")
                lowest, highest = talib.MIN(low, length), talib.MAX(high, length)
                return np.divide(100 * (source - lowest), highest - lowest)
            if name == "sar" and len(args) == 3 and args[0] == args[1]:
                return talib.SAR(
                    self.cache["high"], self.cache["low"], args[1], args[2]
                )
        return super().function(node)


class StagedExpressions(SnapshotExpressions):
    series_type = StagedSeries


@dataclass
class Holding:
    entry: Position
    balance: float = 1.0
    totals: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    orders_filled: set = field(default_factory=set)

    @property
    def size(self):
        return self.entry.size * self.balance

    @property
    def price(self):
        return self.entry.price


@dataclass
class StagedOrder:
    order: PricedOrder
    armed: bool = False

    def fill(self, bar, events):
        levels, direction = self.order.levels, self.order.source.direction
        if not {"stop", "limit"} <= levels.keys():
            return entry_price(levels, direction, bar)
        if not self.armed:
            crossed = entry_price({"stop": levels["stop"]}, direction, bar)
            if crossed is None:
                return None
            self.armed = True
            events["stop-limit activated"] += 1
            if not crossed[1]:
                # The candle's extreme cannot establish a subsequent limit fill.
                return None
        return entry_price({"limit": levels["limit"]}, direction, bar)


class StagedBook:
    """One position, with each bracket reserving an independent share."""

    def __init__(self, tick, events):
        self.tick = tick
        self.events = events
        self.entries = {}
        self.exits = {}
        self.market_exits = []
        self.holding = None
        self.completed = []
        self.cash = []

    def start(self, entry, slot):
        self.holding = Holding(entry)
        self.cash.append((slot, 0.0, -NOTIONAL * FEE, -NOTIONAL * (FEE + EXECUTION)))

    def close(self, fraction, price, slot):
        current = self.holding
        size = min(current.balance, fraction)
        if size <= EPSILON:
            return
        _, gross, fee_only, net = settlement(current.entry, price, slot)
        for i, value in enumerate((gross, fee_only, net)):
            current.totals[i] += size * value
        self.cash.append(
            (
                slot,
                size * gross,
                size * (fee_only + NOTIONAL * FEE),
                size * (net + NOTIONAL * (FEE + EXECUTION)),
            )
        )
        current.balance -= size
        if current.balance > EPSILON:
            self.events["partial exit fill"] += 1
            return
        self.completed.append((slot, *current.totals))
        self.exits.pop(current.entry.identity, None)
        self.holding = None

    @staticmethod
    def fraction(order, holding, *, market=False):
        levels = order.levels
        if "qty" in levels:
            # Absolute quantity is in underlying units under the standardized entry size.
            return levels["qty"] / abs(holding.entry.size)
        if "qty_percent" in levels:
            return levels["qty_percent"] / 100 * (holding.balance if market else 1.0)
        return holding.balance

    def protective_prices(self, order, entry):
        levels = order.levels
        stop = levels.get("stop")
        target = levels.get("limit")
        if stop is None and "loss" in levels:
            stop = entry.price - entry.direction * levels["loss"] * self.tick
        if target is None and "profit" in levels:
            target = entry.price + entry.direction * levels["profit"] * self.tick
        return {k: v for k, v in (("stop", stop), ("limit", target)) if v is not None}

    def protective_fills(self, bar, *, fresh=False, at_open=True):
        if not self.holding:
            return []
        entry = self.holding.entry
        reserved = self.holding.balance
        hits = []
        for identifier, bracket in self.exits.get(entry.identity, {}).items():
            fraction = min(self.fraction(bracket, self.holding), reserved)
            if fraction <= EPSILON:
                continue
            reserved -= fraction
            hit = bracket_price(
                self.protective_prices(bracket, entry),
                entry,
                bar,
                entered_at_open=at_open,
                fresh=fresh,
            )
            if hit:
                hits.append((identifier, fraction, *hit))
        # Each exit reserves a separate tranche. Adverse intrabar fills post first.
        return sorted(hits, key=lambda x: x[3] != "protective stop")

    def apply_protection(self, fills, slot):
        if not self.holding:
            return
        linked = self.holding.entry.identity
        for identifier, fraction, price, kind in fills:
            if not self.holding:
                break
            self.events[kind] += 1
            self.holding.orders_filled.add(identifier)
            self.exits[linked].pop(identifier)
            self.close(fraction, price, slot)

    def advance(self, bar, slot):
        if not trading_bar(bar):
            return
        for order in self.market_exits:
            if self.holding and (
                order.source.action == "close_all"
                or order.source.identity == self.holding.entry.identity
            ):
                size = self.fraction(order, self.holding, market=True)
                self.close(size, bar["open"], slot)
        self.market_exits.clear()
        eligible = []
        for identity, pending in self.entries.items():
            if (
                self.holding
                and pending.order.source.direction == self.holding.entry.direction
            ):
                continue
            fill = pending.fill(bar, self.events)
            if fill:
                eligible.append((identity, pending, *fill))
        protection = self.protective_fills(bar)
        if len(eligible) > 1:
            raise Unsupported("Competing fills require intrabar sequencing")
        if eligible and protection:
            opening_fills = [fill for fill in protection if fill[2] == bar["open"]]
            if eligible[0][3]:
                # A reversal at the open precedes the old position's intrabar exits.
                protection = opening_fills
            elif len(opening_fills) != len(protection):
                raise Unsupported("Competing fills require intrabar sequencing")
        self.apply_protection(protection, slot)
        if eligible:
            identity, pending, price, at_open = eligible[0]
            source = pending.order.source
            self.entries.pop(identity)
            if source.oca_group:
                for k in tuple(self.entries):
                    if self.entries[k].order.source.oca_group == source.oca_group:
                        self.cancel_entry(k)
            if self.holding:
                self.close(self.holding.balance, price, slot)
            self.start(Position(identity, source.direction, price), slot)
            kind = (
                "stop-limit fill"
                if pending.armed
                else "limit entry"
                if "limit" in pending.order.levels
                else "stop entry"
                if "stop" in pending.order.levels
                else "market entry"
            )
            self.events[kind] += 1
            self.apply_protection(
                self.protective_fills(bar, fresh=True, at_open=at_open), slot
            )
        for identity in tuple(self.entries):
            if not self.entries[identity].order.levels:
                self.cancel_entry(identity)

    def cancel_entry(self, identity):
        self.entries.pop(identity, None)
        if not self.holding or self.holding.entry.identity != identity:
            self.exits.pop(identity, None)

    def new_entry(self, order, close):
        source = order.source
        if self.holding and self.holding.entry.direction == source.direction:
            return False
        previous = self.entries.get(source.identity)
        armed = bool(
            previous and previous.armed and previous.order.levels == order.levels
        )
        if previous and previous.armed and previous.order.levels != order.levels:
            self.events["armed stop-limit replaced"] += 1
        if not armed and {"stop", "limit"} <= order.levels.keys():
            stop = order.levels["stop"]
            if close >= stop if source.direction == 1 else close <= stop:
                armed = True
                self.events["stop-limit activated"] += 1
        self.entries[source.identity] = StagedOrder(order, armed)
        return True

    def submit(self, instructions, close):
        new_entry = False
        for order in instructions:
            source = order.source
            name, kind = source.identity, source.action
            if kind == "entry":
                new_entry = self.new_entry(order, close) or new_entry
            elif kind == "cancel_all":
                self.entries.clear()
                self.exits.clear()
            elif kind == "cancel":
                self.cancel_entry(name)
                for brackets in self.exits.values():
                    brackets.pop(name, None)
            elif kind in {"close", "close_all"}:
                if self.holding and (
                    kind == "close_all" or name == self.holding.entry.identity
                ):
                    self.market_exits.append(order)
            else:
                if not order.levels.keys() & {"stop", "limit", "profit", "loss"}:
                    continue
                active = self.holding.entry.identity if self.holding else None
                targets = set(self.entries)
                if active:
                    targets.add(active)
                for target in sorted(targets):
                    if source.from_entry and source.from_entry != target:
                        continue
                    if target == active and name in self.holding.orders_filled:
                        # A fully filled reserved tranche is a one-shot exit on this entry.
                        continue
                    self.exits.setdefault(target, {})[name] = order
        if new_entry and self.market_exits:
            raise Unsupported(
                "Simultaneous close and entry require native order priority"
            )


def instructions_at(prepared, signals, index):
    instructions = []
    for source, conditions, levels in signals:
        values = [prepared.value(x, index) for x in conditions]
        if not all(math.isfinite(x) and x != 0 for x in values):
            continue
        resolved = {k: prepared.value(expr, index) for k, expr in levels.items()}
        resolved = {k: v for k, v in resolved.items() if math.isfinite(v)}
        if (
            any(v <= 0 for v in resolved.values())
            or resolved.get("qty_percent", 0) > 100
        ):
            raise Unsupported("Size or price outside supported order bounds")
        if source.action == "entry" and set(resolved) != set(levels):
            continue
        if source.action in {"exit", "close"} and (
            set(levels) & {"qty", "qty_percent"}
        ) - set(resolved):
            continue
        instructions.append(PricedOrder(source, resolved))
    return instructions


def replay(program, parts, first, end):
    completed, cash, unresolved, events = {}, {}, {}, {}
    for symbol, groups in parts.items():
        completed[symbol], cash[symbol], unresolved[symbol], events[symbol] = (
            [],
            [],
            0,
            Counter(),
        )
        for times, bars in groups:
            prepared = StagedExpressions(bars, program.variables, TICK[symbol])
            signals = [
                (
                    order,
                    [prepared.compile(x) for x in order.conditions],
                    {k: prepared.compile(x) for k, x in order.prices.items()},
                )
                for order in program.orders
            ]
            book = StagedBook(TICK[symbol], events[symbol])
            for i, (slot, bar) in enumerate(zip(times, bars)):
                if not first <= slot < end:
                    continue
                book.advance(bar, slot)
                prepared.at_close(i, book.holding)
                book.submit(instructions_at(prepared, signals, i), bar["close"])
            completed[symbol].extend(book.completed)
            cash[symbol].extend(book.cash)
            unresolved[symbol] += int(book.holding is not None)
    for ledger in (completed, cash, unresolved, events):
        ledger["BTC + ETH"] = ledger["BTCUSD"] + ledger["ETHUSD"]
    return completed, cash, unresolved, events


def summarize_staged(row, market, period, completed, cash, unresolved, events):
    item = summarize((GROUP, row["name"], market, EXIT), period, completed, unresolved)
    for index, (key, drawdown_key) in enumerate(
        zip(COST_KEYS, ("gross", "fee", "net")), 1
    ):
        dd, pct = drawdown((x[0], x[index]) for x in cash)
        item[drawdown_key + "_dd"], item[drawdown_key + "_dd_pct"] = dd, pct
        item["realized_" + key] = sum(x[index] for x in cash)
    item["events"] = dict(events)
    return item


def run(archive, reference, later):
    guide = json.loads(REFERENCES.read_bytes())
    prior = [
        json.loads((ROOT / f).read_bytes())
        for f in ("delta-fmz-replay.json", "delta-fmz-priced-replay.json")
    ]
    states = {i: s for p in prior for i, s, _ in p["coverage"]}
    pending = {i for i, status in states.items() if not status.startswith("Tested")}
    windows = {}
    for label, begin, end, path in [
        (
            "Reference",
            guide["from_ist"][:10],
            guide["to_ist_exclusive"][:10],
            reference,
        ),
        ("Later", *LATER, later),
    ]:
        candles, hashes = load(path)
        assert (
            hashes
            == prior[0]["candle_sha256"][label]
            == prior[1]["candle_sha256"][label]
        )
        first, last = stamp(begin), stamp(end)
        windows[label] = (segments(candles, first, last), first, last, hashes)
    coverage, results, targets = [], [], Counter()
    np.seterr(all="ignore")
    with (
        ZipFile(archive) as z,
        (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream,
    ):
        for idx, row in enumerate(csv.DictReader(stream), 1):
            if idx not in pending:
                continue
            filename = unquote(row["source_url"].split("/" + FMZ_REF + "/")[-1])
            body = z.read("strategies-" + FMZ_REF + "/" + filename)
            blocks = re.findall(
                r"(?ms)^\x60{3}[^\n]*\n(.*?)^\x60{3}", body.decode("utf8")
            )
            choices = [
                (code, features(source_lines(code, multiline=True)))
                for code in blocks
                if re.search(r"\bstrategy\s*\(", code)
            ]
            choices = [(code, flags) for code, flags in choices if any(flags)]
            if not choices:
                continue
            mode = (
                "Both"
                if all(choices[0][1])
                else "Partial exit"
                if choices[0][1][0]
                else "Stop-limit"
            )
            targets[mode] += 1
            try:
                if len(choices) > 1:
                    raise Unsupported("Multiple Pine scripts in the source document")
                code = choices[0][0]
                interval = re.search(r"(?m)^\s*period\s*:\s*(\S+)\s*$", code)
                label = interval[1] if interval else ""
                program = parse(code, label, priced_orders=True, extended_orders=True)
                partial = any(
                    "qty" in order.prices
                    or (
                        "qty_percent" in order.prices
                        and not full_size_default(
                            order.prices["qty_percent"], program.variables
                        )
                    )
                    for order in program.orders
                    if order.action in {"close", "exit"}
                )
                staged = any(
                    {"stop", "limit"} <= order.prices.keys()
                    for order in program.orders
                    if order.action == "entry"
                )
                if not (partial or staged):
                    raise Unsupported("Source default exits the full position")
                mode = (
                    "Both"
                    if partial and staged
                    else "Partial exit"
                    if partial
                    else "Stop-limit"
                )
                rows = []
                for period, (parts, first, end, _) in windows.items():
                    completed, cash, unresolved, events = replay(
                        program, parts, first, end
                    )
                    for market in completed:
                        r = summarize_staged(
                            row,
                            market,
                            period,
                            completed[market],
                            cash[market],
                            unresolved[market],
                            events[market],
                        )
                        r.update(
                            id=idx,
                            source=row["source_url"],
                            archive_interval=label,
                            source_sha256=hashlib.sha256(body).hexdigest(),
                            order_family=mode,
                        )
                        rows.append(r)
            except Unsupported as exc:
                coverage.append([idx, "FMZ partial / staged pending", f"{mode}: {exc}"])
                continue
            except (ValueError, IndexError, TypeError, ArithmeticError) as exc:
                coverage.append(
                    [
                        idx,
                        "FMZ partial / staged pending",
                        f"{mode}: unsupported input ({type(exc).__name__})",
                    ]
                )
                continue
            results.extend(rows)
            status = (
                "Tested · FMZ partial / staged"
                if any(x["trades"] for x in rows)
                else "Tested · FMZ staged, no closes"
            )
            coverage.append(
                [
                    idx,
                    status,
                    f"{mode}: 5m source order replay with staged activation and cash drawdown",
                ]
            )
    return {
        "results": results,
        "coverage": coverage,
        "candidate_modes": dict(targets),
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
    print(report["candidate_modes"], Counter(x[1] for x in report["coverage"]))
