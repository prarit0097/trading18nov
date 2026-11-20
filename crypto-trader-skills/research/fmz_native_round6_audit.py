"""Re-audit pinned FMZ native source and record each independent replay blocker."""

import argparse
import ast
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.fmz_native_expanded_replay import BLOCKS

ROOT = Path(__file__).parent
BASE = ROOT / "remaining-backtest-round5-coverage.json"
SCOPE = {
    "FMZ native offline replay pending",
    "FMZ implicit strategy pending",
    "Pending · FMZ source or data",
}
BINDINGS = {
    "_G",
    "Dial",
    "GetCommand",
    "HttpQuery",
    "HttpQuery_Go",
    "DBExec",
    "Mail",
    "__Serve",
    "__Thread",
    "__threadGetData",
    "__threadSetData",
    "EventLoop",
    "GetDepth",
    "GetRawJSON",
    "GetTrades",
    "GetMarkets",
    "IO",
    "Go",
    "SetCurrency",
    "SetContractType",
    "SetDirection",
    "GetPosition",
    "GetTickers",
    "eval",
    "Function",
}
ACTIONS = {
    "Buy",
    "Sell",
    "BatchOrder",
    "CreateOrder",
    "PlaceOrder",
    "opentrade",
    "closetrade",
}
FORMULA = re.compile(r"\b(?:BK|SK|BP|SP|BPK|SPK|BUY|SELL)\b", re.IGNORECASE)
QUOTED = re.compile(
    r"""//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`"""
)
PINE = {"pinescript", "pine"}
NATIVE = {"javascript", "js", "python", "cpp", "pascal", "c++"}
SKIP_ACTIONS = {
    1123: "The example scans for three black crows, can place one sell and stops. It defines no position lifecycle.",
    1382: "The buy iceberg executes a supplied parent order. It defines no trading entry signal or closing strategy.",
    1383: "The sell iceberg executes a supplied parent order using existing inventory. It defines no entry or closing strategy.",
    4840: "The order API demo places test orders to demonstrate market and limit calls. It defines no historical signal.",
    4920: "The buy iceberg executes a supplied parent order. It defines no trading entry signal or closing strategy.",
    4921: "The sell iceberg executes a supplied parent order using existing inventory. It defines no entry or closing strategy.",
    4926: "The trailing take-profit helper watches the high and sells a caller-supplied amount from existing inventory. The archive defines no historical entry.",
    5139: "The fixed-price stop only sells already held inventory. It defines no entry history or signal.",
}
UTILITIES = {
    "Charting or display": {
        128,
        213,
        218,
        230,
        390,
        453,
        461,
        567,
        687,
        690,
        695,
        945,
        951,
        958,
        1109,
        1122,
        1390,
        2380,
        2385,
        2450,
        2451,
        3738,
        3846,
        3847,
        4353,
        4356,
        4570,
        4646,
        4788,
        4837,
        4838,
        4865,
        4911,
        5183,
        5310,
    },
    "Account observation": {
        127,
        129,
        130,
        135,
        638,
        640,
        653,
        685,
        1110,
        1365,
        1848,
        2394,
        2395,
        3889,
        4147,
        4355,
        4395,
        4408,
        4409,
        4668,
        4947,
        5185,
        5287,
        5298,
        5317,
        5318,
    },
    "Market-data or metadata utility": {
        136,
        139,
        244,
        386,
        397,
        454,
        455,
        636,
        637,
        641,
        648,
        654,
        862,
        863,
        864,
        1042,
        1043,
        1103,
        1111,
        1112,
        1115,
        1202,
        1296,
        1300,
        1308,
        2392,
        2393,
        2396,
        2440,
        2441,
        3744,
        3888,
        4146,
        4402,
        4404,
        4407,
        4419,
        4524,
        4525,
        4526,
        4527,
        4647,
        4786,
        4793,
        4839,
        4861,
        4863,
        4893,
        5184,
        5207,
        5283,
        5284,
        5285,
        5286,
        5301,
        5302,
        5320,
        5495,
        5496,
        5541,
    },
    "API helper, UI control or notification": {
        114,
        205,
        242,
        243,
        360,
        362,
        363,
        377,
        624,
        689,
        925,
        998,
        999,
        1036,
        1041,
        1113,
        1120,
        1289,
        1321,
        1334,
        1386,
        1387,
        1388,
        1393,
        1398,
        1861,
        2381,
        4145,
        4354,
        4376,
        4709,
        4718,
        4767,
        4841,
        4842,
        4843,
        4901,
        4967,
        5279,
        5311,
        5312,
        5612,
        5613,
    },
    "Order/account administration": {
        478,
        639,
        645,
        2382,
        4386,
        4405,
        4410,
        4412,
        4421,
        4424,
        4430,
        4610,
        4657,
        4683,
        4890,
        4891,
        4892,
    },
}
UTILITY_KIND = {i: label for label, ids in UTILITIES.items() for i in ids}
assert len(UTILITY_KIND) == sum(map(len, UTILITIES.values()))
NON_TRADE_NOTE = {
    4387: "The source values scheduled contributions as a mark-to-market series and never defines an exit or order lifecycle.",
}
VERIFIED_INPUTS = {
    831: "The archived ATR sizing uses a 1 BCH treasury and hard-coded BTC/BCH and ETH/BCH precision/minimums. Its depth-based order rules need synchronized historical BCH-quoted books.",
    1203: "The source updates internal balances on an OKEX BTC/USDT, LTC/USDT and LTC/BTC triangle using synchronized executable quotes. The original third-leg price and depth still need verification.",
    4681: "The archived DCA loop only permits a buy below a caller-supplied maximum bid price. The source-matched public page exposes zero for that input, so a meaningful market test requires a positive configured threshold.",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def masked(code):
    return QUOTED.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), code)


def locations(code, pattern):
    groups = defaultdict(list)
    for i, line in enumerate(code.splitlines(), 1):
        for name in set(pattern.findall(line)):
            groups[name].append(i)
    return dict(sorted(groups.items()))


ACTION_CALLS = re.compile(r"\.\s*(" + "|".join(sorted(ACTIONS)) + r")\s*\(")
BINDING_CALLS = re.compile(r"\b(" + "|".join(sorted(BINDINGS)) + r")\s*\(")
PINE_CALLS = re.compile(r"\bstrategy\.(entry|order|exit|close|close_all)\s*\(")
OBSERVER_CALLS = re.compile(
    r"\b(Chart|KLineChart|PlotRecords|PlotLine|LogStatus|LogProfit|GetTicker|GetRecords|"
    r"GetAccount|GetOrders|GetAssets|CancelOrder|GetPosition|GetName)\s*\("
)


def evidence(language, source):
    cleaned = masked(source)
    settings = re.search(r"(?is)/\*\s*backtest.*?\*/", source)
    imports, declarations = set(), set()
    if language == "python":
        try:
            tree = ast.parse(source.lstrip("\ufeff"))
        except SyntaxError:
            parsed = False
        else:
            parsed = True
            actions, bindings = defaultdict(list), defaultdict(list)
            entry = any(
                isinstance(x, ast.FunctionDef) and x.name == "main" for x in tree.body
            )
            dynamic = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(a.name.split(".")[0] for a in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else func.id
                    if isinstance(func, ast.Name)
                    else ""
                )
                dynamic |= isinstance(func, (ast.Subscript, ast.Call)) or name in {
                    "getattr",
                    "__getattribute__",
                }
                if isinstance(func, ast.Attribute) and name in ACTIONS:
                    actions[name].append(node.lineno)
                if name in BINDINGS:
                    bindings[name].append(node.lineno)
    else:
        parsed = None
    if parsed is not True:
        actions, bindings = (
            locations(cleaned, ACTION_CALLS),
            locations(cleaned, BINDING_CALLS),
        )
        entry = bool(
            re.search(r"\b(?:function\s+main|int\s+main|def\s+main)\s*\(", cleaned)
        )
        dynamic = bool(
            re.search(
                r"\[\s*[^\]\n]+\s*\]\s*\(|\b(?:getattr|eval|Function)\s*\(", cleaned
            )
        )
    if language in PINE:
        declarations = set(
            re.findall(r"(?m)^\s*(strategy|indicator|study)\s*\(", cleaned)
        )
        actions = locations(cleaned, PINE_CALLS)
    formula = (
        sorted(set(FORMULA.findall(cleaned)) & {"BK", "SK", "BP", "SP", "BPK", "SPK"})
        if language == "pascal"
        else []
    )
    return {
        "language": language or "untagged",
        "sha256": digest(source.encode()),
        "lines": len(source.splitlines()),
        "entrypoint": entry,
        "actions": {k: sorted(set(v)) for k, v in sorted(actions.items())},
        "bindings": {k: sorted(set(v)) for k, v in sorted(bindings.items())},
        "observer_calls": locations(cleaned, OBSERVER_CALLS),
        "imports": sorted(imports),
        "declarations": sorted(declarations),
        "dynamic_dispatch": dynamic,
        "formula_actions": formula,
        "python_ast": parsed,
        "archived_backtest_header": bool(settings),
    }


def state(row, blocks, duplicates):
    id_, prior = row["id"], row["reason"]
    active = [
        b
        for b in blocks
        if b["language"] in NATIVE | PINE or b["entrypoint"] or b["actions"]
    ]
    if id_ in SKIP_ACTIONS:
        return "Excluded · FMZ execution utility or example", SKIP_ACTIONS[id_]
    if id_ in NON_TRADE_NOTE:
        return "Excluded · FMZ valuation example", NON_TRADE_NOTE[id_]
    if id_ in VERIFIED_INPUTS:
        return "Pending · FMZ verified input dependency", VERIFIED_INPUTS[id_]
    if (
        id_ in UTILITY_KIND
        and active
        and not any(
            b["actions"] or b["formula_actions"] or b["python_ast"] is False
            for b in active
        )
    ):
        kind = UTILITY_KIND[id_]
        return (
            "Excluded · FMZ standalone utility",
            f"{kind}. The archived source supplies no standalone BTC/ETH entry and closing rules.",
        )
    if active and all(
        b["language"] in PINE
        and set(b["declarations"]) <= {"indicator", "study"}
        and b["declarations"]
        and not b["actions"]
        for b in active
    ):
        return (
            "Excluded · FMZ indicator without orders",
            "The archived Pine declaration is an indicator or study and contains no native strategy order calls.",
        )
    if active and all(
        b["language"] in PINE
        and set(b["declarations"]) <= {"indicator", "study"}
        and b["declarations"]
        and b["actions"]
        for b in active
    ):
        return (
            "Pending · FMZ Pine declaration conversion",
            "The archived Pine source declares an indicator or study and also calls strategy orders. It needs a source-backed strategy declaration and replay verification.",
        )
    if (
        prior.startswith(
            ("No native order placement", "No standalone native trading orders")
        )
        and active
        and all(
            b["language"] in NATIVE
            and (b["language"] != "python" or b["python_ast"] is True)
            and not b["actions"]
            and not b["dynamic_dispatch"]
            and not b["formula_actions"]
            and not set(b["bindings"])
            & {"IO", "Go", "Dial", "HttpQuery", "GetCommand", "eval", "Function"}
            for b in active
        )
        and not duplicates
    ):
        return (
            "Pending · FMZ source function review",
            f"{prior}. Pinned block review found no direct order call; indirect template or method invocation needs source-level verification.",
        )
    if duplicates:
        return (
            "Pending · FMZ source equivalence",
            f"{prior}. Exact executable block match with catalogue IDs {', '.join(map(str, duplicates))}; the original settings still need equivalence verification.",
        )
    return row["status"], prior


def run(archive, output):
    baseline = [r for r in read(BASE)["disposition"] if r["status"] in SCOPE]
    signatures = defaultdict(list)
    rows = []
    with ZipFile(archive) as source:
        for r in baseline:
            prefix, tail = r["source"].split(f"/{FMZ_REF}/", 1)
            assert prefix == "https://github.com/fmzquant/strategies/blob"
            raw = source.read(f"strategies-{FMZ_REF}/{unquote(tail)}")
            if r.get("pinned_document_sha256"):
                assert digest(raw) == r["pinned_document_sha256"]
            blocks = [
                evidence(language.strip().lower(), code)
                for language, code in BLOCKS.findall(raw.decode("utf-8-sig"))
            ]
            signature = tuple(
                b["sha256"] for b in blocks if b["entrypoint"] or b["actions"]
            )
            if signature:
                signatures[signature].append(r["id"])
            rows.append((r, digest(raw), blocks, signature))
    coverage, evidence_rows = [], []
    for r, document, blocks, signature in rows:
        duplicates = [i for i in signatures.get(signature, ()) if i != r["id"]]
        status, reason = state(r, blocks, duplicates)
        coverage.append([r["id"], status, reason])
        evidence_rows.append(
            {
                "id": r["id"],
                "document_sha256": document,
                "blocks": blocks,
                "same_executable_blocks": duplicates,
            }
        )
    assert len(coverage) == len({i for i, *_ in coverage}) == 454
    write(
        output,
        {
            "baseline": "91ad53db",
            "source_revision": FMZ_REF,
            "source_archive_sha256": digest(archive.read_bytes()),
            "coverage": coverage,
            "results": [],
            "source_evidence": evidence_rows,
        },
    )
    print(dict(Counter(row[1] for row in coverage)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    run(**vars(parser.parse_args()))
