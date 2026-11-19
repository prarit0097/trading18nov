"""Replay the auditable market-order subset of pinned FMZ Pine examples on Delta.

Run alongside delta_strategy_replay with TA-Lib 0.6.8 and NumPy installed.
Only public candles and source documents are read. Original Pine never executes.
"""

import argparse
import ast
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
import csv
import hashlib
import json
import re
from urllib.parse import unquote
from zipfile import ZipFile

import numpy as np
import talib

from research.delta_strategy_replay import (
    BAR,
    COINS,
    LATER,
    REFERENCES,
    ROOT,
    load,
    stamp,
    summarize,
    trading_bar,
    fill,
)

FMZ_REF = "7853bb2bf262c4567ac238d3552d97f0e50cb801"
GROUP = "FMZ market-order ports"
EXIT = "Source market exits"
IMPLICIT_PLOTS = {
    "barcolor",
    "bgcolor",
    "plot",
    "plotshape",
    "plotchar",
    "hline",
    "fill",
    "alertcondition",
}
BASE = {"open", "close", "high", "low", "volume", "hl2", "hlc3", "ohlc4", "oc2"}


class Unsupported(ValueError):
    """Source uses features outside the evaluator's documented subset."""


@dataclass
class Order:
    action: str
    identity: str
    direction: int
    conditions: tuple
    prices: dict = field(default_factory=dict)
    from_entry: str = ""
    oca_group: str = ""


@dataclass
class Program:
    variables: dict
    orders: list
    archived_interval: str


def transform(expression):
    # Convert only expression syntax. The AST is interpreted by the allowlist below.
    expression = expression.strip()
    if expression.startswith("(") and expression.endswith(")"):
        level = 0
        for i, c in enumerate(expression):
            level += (c == "(") - (c == ")")
            if level == 0:
                if i == len(expression) - 1:
                    return "(" + transform(expression[1:-1]) + ")"
                break
    level = 0
    pending = 0
    conditional = None
    for i, ch in enumerate(expression):
        if ch in "([":
            level += 1
        elif ch in ")]":
            level -= 1
        elif level == 0 and ch == "?":
            if conditional is None:
                conditional = i
            pending += 1
        elif level == 0 and ch == ":" and conditional is not None:
            pending -= 1
            if not pending:
                return (
                    f"iff({transform(expression[:conditional])},"
                    f"{transform(expression[conditional + 1 : i])},{transform(expression[i + 1 :])})"
                )
    return expression


def expression(text):
    try:
        return ast.parse(transform(text), mode="eval").body
    except SyntaxError as exc:
        raise Unsupported("Expression syntax outside subset") from exc


def call_parts(line):
    call = expression(line)
    if not isinstance(call, ast.Call):
        raise Unsupported("Expected a function call")
    return call.args, {k.arg: k.value for k in call.keywords}


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise Unsupported("Order uses a computed identifier or parameter") from exc


def parse(code, interval, *, priced_orders=False):
    # Captures ordinary quote-delimited string literals and removes comments without touching them.
    comment = re.compile(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|//.*""")
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    lines = [
        (len(line.expandtabs(4)) - len(line.lstrip().expandtabs(4)), line.strip())
        for raw in code.splitlines()
        if (line := comment.sub(lambda m: m[1] or "", raw).rstrip()).strip()
    ]
    variables, orders = {}, []
    stack = []
    previous_if = {}
    found_header = False
    for indent, line in lines:
        while stack and indent <= stack[-1][0]:
            stack.pop()
        for depth in tuple(previous_if):
            if depth > indent:
                previous_if.pop(depth)
        prior_if = previous_if.pop(indent, None)
        if re.match(r"strategy\s*\(", line):
            _, kw = call_parts(line)
            unsafe = {
                "process_orders_on_close",
                "calc_on_order_fills",
                "calc_on_every_tick",
                "use_bar_magnifier",
                "pyramiding",
            }
            if any(
                key in kw
                and not (isinstance(kw[key], ast.Name) and kw[key].id == "false")
                and literal(kw[key]) not in (0, 1, False)
                for key in sorted(unsafe)
            ):
                raise Unsupported("Nonstandard Pine execution configuration")
            if any(
                key in kw
                and not (isinstance(kw[key], ast.Name) and kw[key].id == "false")
                and literal(kw[key])
                for key in sorted(unsafe - {"pyramiding"})
            ):
                raise Unsupported("Nonstandard Pine order timing")
            found_header = True
        elif line.startswith("if ") or line.startswith("if("):
            condition = expression(line[2:])
            stack.append((indent, condition))
            previous_if[indent] = condition
        elif priced_orders and line == "else" and prior_if is not None:
            stack.append((indent, ast.UnaryOp(op=ast.Not(), operand=prior_if)))
        elif match := re.match(r"strategy\.(\w+)\s*\(", line):
            kind = match[1]
            args, kw = call_parts(line)
            supported = {"entry", "close", "close_all"}
            if priced_orders:
                supported |= {"exit", "cancel", "cancel_all"}
            if kind not in supported:
                raise Unsupported("Stop, limit, cancel or other order model")
            allowed = {"when", "comment", "alert_message"}
            maximum = {
                "entry": 2,
                "close": 1,
                "close_all": 0,
                "exit": 2,
                "cancel": 1,
                "cancel_all": 0,
            }
            if kind == "entry":
                allowed.update(("id", "direction"))
                if priced_orders:
                    allowed.update(("stop", "limit", "oca_name", "oca_type"))
            if kind in {"close", "cancel"}:
                allowed.add("id")
            if kind == "exit":
                allowed.update(
                    (
                        "id",
                        "from_entry",
                        "stop",
                        "limit",
                        "loss",
                        "profit",
                        "qty_percent",
                        "comment_profit",
                        "comment_loss",
                        "alert_profit",
                        "alert_loss",
                    )
                )
                if "qty_percent" in kw and literal(kw["qty_percent"]) != 100:
                    raise Unsupported(
                        "Partial protective exit requires a quantity model"
                    )
                if not (set(kw) & {"stop", "limit", "profit", "loss"}):
                    raise Unsupported("Missing bracket price")
            if priced_orders and kind == "entry" and {"stop", "limit"} <= set(kw):
                raise Unsupported("Stop-limit entry requires a two-stage fill model")
            if set(kw) - allowed or len(args) > maximum[kind]:
                raise Unsupported("Stop, limit, sizing or fill parameter")
            direction = 0
            identity = ""
            if kind not in {"close_all", "cancel_all"}:
                identity = literal(args[0] if args else kw.get("id"))
                if not isinstance(identity, str):
                    raise Unsupported("Unsupported order identifier")
            if kind == "entry":
                side = args[1] if len(args) > 1 else kw.get("direction")
                if (
                    not isinstance(side, ast.Attribute)
                    or not isinstance(side.value, ast.Name)
                    or side.value.id != "strategy"
                    or side.attr not in {"long", "short"}
                ):
                    raise Unsupported("Computed direction")
                direction = 1 if side.attr == "long" else -1
            conditions = [node for _, node in stack]
            if "when" in kw:
                conditions.append(kw["when"])
            linked = (
                literal(args[1] if len(args) > 1 else kw["from_entry"])
                if kind == "exit" and (len(args) > 1 or "from_entry" in kw)
                else ""
            )
            group = ""
            if "oca_type" in kw:
                mode = ast.unparse(kw["oca_type"])
                if mode not in {"strategy.oca.none", "strategy.oca.cancel"}:
                    raise Unsupported("Unsupported OCA order reduction")
                if mode.endswith(".cancel") and "oca_name" in kw:
                    group = literal(kw["oca_name"])
            prices = {k: kw[k] for k in ("stop", "limit", "loss", "profit") if k in kw}
            orders.append(
                Order(
                    kind, identity, direction, tuple(conditions), prices, linked, group
                )
            )
        elif re.match(r"(?:" + "|".join(IMPLICIT_PLOTS) + r")\s*\(", line):
            continue
        elif (
            not stack
            and (
                match := re.fullmatch(
                    r"(?:float |int |bool |color )?(\w+)\s*=\s*(.+)"
                    if priced_orders
                    else r"(\w+)\s*=\s*(.+)",
                    line,
                )
            )
            and match[1] not in variables
        ):
            # Parse only reachable variables so a drawing expression cannot invalidate clean order logic.
            variables[match[1]] = match[2]
        else:
            raise Unsupported(
                "Stateful, nested, multiline or unsupported source syntax"
            )
    if not found_header or not any(o.action == "entry" for o in orders):
        raise Unsupported("No supported market entry")
    if (
        len({o.identity for o in orders if o.action == "entry" and o.direction > 0}) > 1
        or len({o.identity for o in orders if o.action == "entry" and o.direction < 0})
        > 1
    ):
        raise Unsupported("Multiple entry IDs on one side")
    return Program(variables, orders, interval)


MATH = {
    "abs": np.abs,
    "log": np.log,
    "sqrt": np.sqrt,
    "sign": np.sign,
    "round": lambda x: np.floor(x + 0.5),
    "pow": np.power,
    "ceil": np.ceil,
    "floor": np.floor,
    "min": np.minimum,
    "max": np.maximum,
}
TA = {
    "sma": talib.SMA,
    "ema": talib.EMA,
    "wma": talib.WMA,
    "stdev": talib.STDDEV,
    "roc": talib.ROC,
    "mom": talib.MOM,
    "correlation": talib.CORREL,
    "highest": talib.MAX,
    "lowest": talib.MIN,
    "rsi": talib.RSI,
    "sum": talib.SUM,
    "linreg": talib.LINEARREG,
}


class Series:
    def __init__(self, bars, variables):
        self.size = len(bars)
        self.vars = variables
        self.cache = {
            k: np.array([b[k] for b in bars], dtype=float) for k in BASE & set(bars[0])
        }
        h, l, c, o = (self.cache[k] for k in ("high", "low", "close", "open"))
        self.cache.update(
            hl2=(h + l) / 2,
            hlc3=(h + l + c) / 3,
            ohlc4=(o + h + l + c) / 4,
            oc2=(o + c) / 2,
        )
        self.active = set()
        self.cache.update(true=True, false=False)

    def array(self, x):
        if isinstance(x, np.ndarray):
            return x.astype(float, copy=False)
        if not isinstance(x, (float, int, bool, np.number)):
            raise Unsupported("Unsupported series type")
        return np.full(self.size, x, dtype=float)

    @staticmethod
    def scalar_int(x):
        if (
            not isinstance(x, (int, float, np.number))
            or not np.isfinite(x)
            or int(x) != x
            or not 0 <= x <= 2000
        ):
            raise Unsupported("Length or lag outside supported bounds")
        return int(x)

    def lag(self, x, k):
        x = self.array(x)
        if not k:
            return x
        a = np.full(self.size, np.nan)
        if k < self.size:
            a[k:] = x[:-k]
        return a

    def truth(self, arg):
        x = self.array(arg)
        return np.isfinite(x) & (x != 0)

    def evaluate(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            key = node.id
            if key not in self.cache:
                if key == "na":
                    return float("nan")
                if key not in self.vars or key in self.active:
                    raise Unsupported("External or recursive series dependency")
                self.active.add(key)
                self.cache[key] = self.evaluate(expression(self.vars[key]))
                self.active.remove(key)
            return self.cache[key]
        if isinstance(node, ast.Subscript):
            return self.lag(
                self.evaluate(node.value), self.scalar_int(self.evaluate(node.slice))
            )
        if isinstance(node, ast.UnaryOp) and type(node.op) in (
            ast.Not,
            ast.UAdd,
            ast.USub,
        ):
            value = self.evaluate(node.operand)
            if isinstance(node.op, ast.Not):
                return ~self.truth(value)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BoolOp) and type(node.op) in (ast.And, ast.Or):
            op = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
            return op.reduce([self.truth(self.evaluate(x)) for x in node.values])
        if isinstance(node, ast.BinOp):
            op = {
                ast.Add: np.add,
                ast.Sub: np.subtract,
                ast.Mult: np.multiply,
                ast.Div: np.divide,
                ast.Pow: np.power,
                ast.Mod: np.mod,
            }.get(type(node.op))
            if op is not None:
                return op(self.evaluate(node.left), self.evaluate(node.right))
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            op = {
                ast.Lt: np.less,
                ast.LtE: np.less_equal,
                ast.Gt: np.greater,
                ast.GtE: np.greater_equal,
                ast.Eq: np.equal,
                ast.NotEq: np.not_equal,
            }.get(type(node.ops[0]))
            if op is not None:
                a, b = self.evaluate(node.left), self.evaluate(node.comparators[0])
                return np.isfinite(a) & np.isfinite(b) & op(a, b)
        if isinstance(node, ast.Call):
            return self.function(node)
        raise Unsupported("Expression operator outside supported subset")

    def function(self, node):
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            scope = node.func.value.id
            if scope not in {"ta", "math", "input"}:
                raise Unsupported("External or unsupported function")
            if scope == "input" and node.func.attr not in {
                "source",
                "int",
                "float",
                "bool",
            }:
                raise Unsupported("Input type outside subset")
            name = "input" if scope == "input" else node.func.attr
        else:
            raise Unsupported("Unsupported function form")
        if name == "input":
            default = next(
                (k.value for k in node.keywords if k.arg == "defval"),
                node.args[0] if node.args else None,
            )
            if default is None:
                raise Unsupported("No input default")
            return self.evaluate(default)
        if node.keywords:
            raise Unsupported("Named function arguments outside subset")
        args = [self.evaluate(a) for a in node.args]
        if name in MATH:
            first = args[0]
            if name in {"min", "max"}:
                for value in args[1:]:
                    first = MATH[name](first, value)
                return first
            return MATH[name](*args)
        if name == "iff" and len(args) == 3:
            return np.where(self.truth(args[0]), args[1], args[2])
        if name == "na" and len(args) == 1:
            return ~np.isfinite(args[0])
        if name == "nz" and len(args) in (1, 2):
            return np.where(
                np.isfinite(args[0]), args[0], args[1] if len(args) == 2 else 0
            )
        if name in {"crossover", "crossunder", "cross"} and len(args) == 2:
            a, b = args
            before_a, before_b = self.lag(a, 1), self.lag(b, 1)
            # Ignore floating-point drift when rolling averages are mathematically equal.
            before_equal = np.isclose(before_a, before_b, rtol=1e-12, atol=1e-12)
            different_now = ~np.isclose(a, b, rtol=1e-12, atol=1e-12)
            up = different_now & (a > b) & ((before_a < before_b) | before_equal)
            down = different_now & (a < b) & ((before_a > before_b) | before_equal)
            return (
                up
                if name == "crossover"
                else down
                if name == "crossunder"
                else up | down
            )
        if name == "change" and len(args) in (1, 2):
            return args[0] - self.lag(
                args[0], self.scalar_int(args[1]) if len(args) == 2 else 1
            )
        if name in {"atr", "cci", "mfi"} and len(args) in (1, 2):
            n = self.scalar_int(args[-1])
            if n < 2:
                raise Unsupported("Unsupported ATR, CCI or MFI length")
            h, l, c = (self.cache[x] for x in ("high", "low", "close"))
            if name == "atr" and len(args) == 1:
                return talib.ATR(h, l, c, n)
            if (
                name == "mfi"
                and len(args) == 2
                and np.array_equal(args[0], (h + l + c) / 3)
            ):
                return talib.MFI(h, l, c, self.cache["volume"], n)
            if name == "cci" and len(args) == 2:
                x = self.array(args[0])
                return talib.CCI(x, x, x, n)
        if name in TA:
            if len(args) == 1 and name in {"highest", "lowest"}:
                args.insert(0, self.cache["high" if name == "highest" else "low"])
            expected = 3 if name == "correlation" or name == "linreg" else 2
            if len(args) == expected:
                if name == "linreg" and self.scalar_int(args[-1]) != 0:
                    raise Unsupported("Linear regression offset outside subset")
                length = self.scalar_int(args[-2 if name == "linreg" else -1])
                values = args[:1] if name == "linreg" else args[:-1]
                series = [self.array(x) for x in values]
                if length == 1 and name in {
                    "sma",
                    "ema",
                    "wma",
                    "highest",
                    "lowest",
                    "sum",
                }:
                    return series[0]
                if length == 1 and name == "stdev":
                    return series[0] * 0
                if length < 1 or length == 1 and name not in {"mom", "roc"}:
                    raise Unsupported("Unsupported indicator lookback")
                for x in series:
                    finite = np.flatnonzero(np.isfinite(x))
                    if finite.size and not np.all(np.isfinite(x[finite[0] :])):
                        raise Unsupported("Indicator requires sparse-source semantics")
                return TA[name](*series, length)
        raise Unsupported("Function outside supported subset")

    def masks(self, program):
        masks = []
        for order in program.orders:
            mask = np.ones(self.size, dtype=bool)
            for node in order.conditions:
                mask &= self.truth(self.evaluate(node))
            masks.append(mask)
        return masks


def segments(candles, first, end):
    out = {}
    for symbol in COINS:
        items = sorted(t for t in candles[symbol] if first - 288 * BAR <= t < end)
        out[symbol] = []
        for _, seq in groupby(enumerate(items), key=lambda x: x[1] - x[0] * BAR):
            times = [t for _, t in seq]
            out[symbol].append((times, [candles[symbol][t] for t in times]))
    return out


def replay(program, candle_index, parts, first, end):
    values, missing = {}, {}
    for symbol, groups in parts.items():
        trades = []
        active = None
        for times, bars in groups:
            evaluator = Series(bars, program.variables)
            masks = evaluator.masks(program)
            for k, t in enumerate(times):
                slot = t + BAR
                if not first <= slot < end or not trading_bar(
                    candle_index[symbol].get(slot)
                ):
                    continue
                available = [
                    order for order, mask in zip(program.orders, masks) if mask[k]
                ]
                entries = [o for o in available if o.action == "entry"]
                if len(entries) > 1:
                    raise Unsupported(
                        "Simultaneous market entries require Pine order priority"
                    )
                closes = [
                    o
                    for o in available
                    if o.action != "entry"
                    and active
                    and (o.action == "close_all" or o.identity == active[1].identity)
                ]
                if entries and closes:
                    raise Unsupported(
                        "Simultaneous entry and explicit close require broker ordering"
                    )
                next_order = entries[0] if entries else None
                if active and (
                    closes
                    or (next_order and next_order.direction != active[1].direction)
                ):
                    trades.append(
                        fill(
                            [(symbol, active[1].direction)],
                            active[0],
                            slot,
                            candle_index,
                        )
                    )
                    active = None
                if next_order and active is None:
                    active = (slot, next_order)
        values[symbol] = trades
        missing[symbol] = int(active is not None)
    values["BTC + ETH"] = values["BTCUSD"] + values["ETHUSD"]
    missing["BTC + ETH"] = missing["BTCUSD"] + missing["ETHUSD"]
    return values, missing


def run(archive, reference, later):
    manifests = json.loads(REFERENCES.read_bytes())
    windows = {}
    for period, begin, end, path in (
        (
            "Reference",
            manifests["from_ist"][:10],
            manifests["to_ist_exclusive"][:10],
            reference,
        ),
        ("Later", *LATER, later),
    ):
        candles, hashes = load(path)
        if period == "Reference":
            assert all(hashes[s] == manifests["candle_sha256"][s] for s in COINS)
        first, stop = stamp(begin), stamp(end)
        windows[period] = (candles, segments(candles, first, stop), first, stop, hashes)
    results, coverage = [], []
    np.seterr(all="ignore")
    with (
        ZipFile(archive) as z,
        (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream,
    ):
        for idx, row in enumerate(csv.DictReader(stream), 1):
            if row["source"] != "FMZ":
                continue
            if not re.search(
                r"\b(?:BTC|ETH)_(?:USD|USDT|USDC)\b", row["market_or_pair"]
            ):
                continue
            filename = unquote(row["source_url"].split("/" + FMZ_REF + "/")[-1])
            raw = z.read("strategies-" + FMZ_REF + "/" + filename)
            doc = raw.decode("utf8")
            matches = re.findall(r"(?ms)^\x60{3}[^\n]*\n(.*?)^\x60{3}", doc)
            codes = [
                b
                for b in matches
                if re.search(r"\bstrategy\s*\(", b) and "strategy.entry" in b
            ]
            if len(codes) != 1:
                coverage.append(
                    [
                        idx,
                        "FMZ native source pending",
                        "No single Pine market-entry script in the document",
                    ]
                )
                continue
            code = codes[0]
            interval = re.search(r"(?m)^\s*period\s*:\s*(\S+)\s*$", code)
            label = interval[1] if interval else ""
            try:
                program = parse(code, label)
                strategy_results = []
                for period, (candles, parts, first, end, _) in windows.items():
                    samples, missing = replay(program, candles, parts, first, end)
                    for name, sample in samples.items():
                        summary = summarize(
                            (GROUP, row["name"], name, EXIT),
                            period,
                            sample,
                            missing[name],
                        )
                        summary.update(
                            id=idx,
                            source=row["source_url"],
                            archive_interval=label,
                            source_sha256=hashlib.sha256(raw).hexdigest(),
                        )
                        strategy_results.append(summary)
            except Unsupported as exc:
                coverage.append([idx, "FMZ source port pending", str(exc)])
                continue
            except (ValueError, IndexError, TypeError, ArithmeticError) as exc:
                coverage.append(
                    [
                        idx,
                        "FMZ source port pending",
                        f"Indicator or input combination outside subset ({type(exc).__name__})",
                    ]
                )
                continue
            results.extend(strategy_results)
            status = (
                "Tested · FMZ port"
                if any(x["trades"] for x in strategy_results)
                else "Tested · no closed fills"
            )
            coverage.append(
                [idx, status, "5m Delta market-order port with source signal exits"]
            )
    return {
        "results": results,
        "coverage": coverage,
        "candle_sha256": {n: w[-1] for n, w in windows.items()},
        "pinned_fmz_ref": FMZ_REF,
        "libraries": {"talib": talib.__version__, "numpy": np.__version__},
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "reference", "later", "output"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    result = run(args.archive, args.reference, args.later)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf8",
        newline="\n",
    )
    print(Counter(s[1] for s in result["coverage"]))
