"""Index standalone Python sources without executing their strategy code."""

import argparse
import ast
import builtins
import json
import re
import symtable
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_native_expanded_replay import BLOCKS

BUILTINS = set(dir(builtins)) | set("""
exchange exchanges main Log LogStatus LogProfit LogReset Sleep _G _C _N _D TA talib
PERIOD_H1 PERIOD_M1 PERIOD_M5 PERIOD_M15 PERIOD_M30 PERIOD_D1 PERIOD_H4 ORDER_STATE_CLOSED
ORDER_TYPE_BUY ORDER_TYPE_SELL ORDER_STATE_PENDING PD_LONG PD_SHORT IsVirtual _Cross Chart _T
ORDER_STATE_CANCELED
""".split())
LOCAL_IMPORTS = set("math time datetime json copy collections decimal statistics fmz".split())
HOST = set("GetCommand HttpQuery Dial _G ext eval exec open compile __import__".split())
MARKET = set("GetDepth GetTrades Go IO GetRawJSON SetCurrency SetProxy GetTickerAll".split())
FUTURES = set("SetContractType SetDirection SetMarginLevel GetPositions GetPosition".split())


def analyze(source):
    ast_root = ast.parse(source)
    symbols = symtable.symtable(source, "archive", "exec")
    declared = {s.get_name() for s in symbols.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    todo = [symbols]
    names = set()
    while todo:
        table = todo.pop()
        todo.extend(table.get_children())
        names.update(s.get_name() for s in table.get_symbols() if s.is_global() and s.is_referenced())
    methods, imports = set(), set()
    for node in ast.walk(ast_root):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("exchange", "e"):
            methods.add(node.attr)
        if isinstance(node, ast.Import):
            imports.update(x.name.split(".")[0] for x in node.names)
        if isinstance(node, ast.ImportFrom):
            imports.add((node.module or "").split(".")[0])
    header = re.search(r"(?s)([\x27\x22]{3})\s*backtest\s+(.*?)\1", source)
    fields = dict(re.findall(r"(?m)^([\w]+):\s*([^\r\n]+)", header[2])) if header else {}
    args = {arg[0]: arg[1] for arg in json.loads(fields["args"]) if len(arg) == 2} if "args" in fields else {}
    reason = None
    for dependencies, label in (
        (imports - LOCAL_IMPORTS, "External import needed"),
        (names & HOST, "External host or stored state"),
        (methods & MARKET, "Original venue inputs for"),
    ):
        if dependencies:
            reason = f"{label}: " + ", ".join(sorted(dependencies))
            break
    if reason is None:
        missing = names - BUILTINS - declared - args.keys()
        if not methods & {"Buy", "Sell", "CreateOrder"}:
            reason = "No standalone native trading orders"
        elif missing:
            reason = "Missing defaults: " + ", ".join(sorted(missing))
        elif methods & FUTURES:
            reason = "Futures execution and funding reconciliation"
    return {"reason": reason, "args": args, "fields": fields, "methods": sorted(methods)}


def run(archive, work):
    index = read(work / "native-source-index.json")
    rows = []
    with ZipFile(archive) as fmz:
        for row in index.values():
            ref, relative = row["source"].split("/blob/", 1)[1].split("/", 1)
            text = fmz.read(f"strategies-{ref}/{unquote(relative)}").decode("utf-8")
            options = [c for t, c in BLOCKS.findall(text) if t.strip() == "python" and re.search(r"(?m)^def\s+main\s*\(", c)]
            if len(options) != 1:
                continue
            code = options[0].lstrip("\ufeff")
            try:
                result = analyze(code)
            except (SyntaxError, ValueError, TypeError, IndexError) as exc:
                result = {"reason": f"Cannot parse Python 3 source: {str(exc)[:110]}"}
            rows.append({**row, "code": code, **result})
    write(work / "native-python-screen.json", rows)
    print(len(rows), "standalone Python source checks", Counter(x["reason"] is None for x in rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("work", type=Path)
    args = parser.parse_args()
    run(args.archive, args.work)
