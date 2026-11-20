"""Record the source evidence for two separately dispositioned FMZ cases."""

import argparse
import ast
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EXECUTION, FEE
from research.fmz_native_round6_audit import BASE, ROOT, digest
from research.fmz_native_round7 import display_settings, header_settings, source

CASES = {
    575: {
        "publisher": "https://www.fmz.com/strategy/356399",
        "snippets": (
            "if result == True and self.Sell == False:",
            "exchanges[self.index].Sell(-1, num)",
        ),
        "status": "Pending · FMZ seeded daily exit overlay",
        "reason": "The complete native Python source is an inventory exit. The original daily Bitfinex BTC/USD configuration seeds 10 BTC and publishes 0.1 BTC per sale, so a historical seeded exit overlay is a viable separate study. The original venue and warm-up boundary must be preserved for exact replay, and a BTC/ETH spot port needs its own label.",
    },
    4681: {
        "publisher": "https://www.fmz.com/strategy/54256",
        "snippets": (
            "depth = exchanges[i].GetDepth()",
            'bidPrice = depth["Asks"][0]["Price"]',
            "if bidPrice <  maxBidPrice :",
            "exchanges[i].Buy(amount)",
        ),
        "status": "Pending · FMZ price ceiling and adapter",
        "reason": "The matched public default maxBidPrice=0 cannot admit any positive ask. The price ceiling is configurable, so this is not a permanent exclusion. A replay needs a source-backed nonzero input, the relevant historical ask series and a verified mapping for the legacy one-argument buy call.",
    },
}


def generate(archive, work, output):
    catalogue = {i["id"]: i for i in read(BASE)["disposition"]}
    matched = {
        item["id"]: item
        for item in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
    }
    results, coverage = [], []
    with ZipFile(archive) as pinned:
        for ident, spec in CASES.items():
            link = catalogue[ident]["source"]
            document, code = source(pinned, link)
            assert digest(document) == matched[ident]["document_sha256"]
            assert spec["publisher"].encode() in document
            public = display_settings(work, ident, code)
            tree = ast.parse(code)
            trade_calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.casefold()
                in {
                    "buy",
                    "sell",
                    "createorder",
                    "placeorder",
                    "createtrade",
                }
            ]
            assert len(trade_calls) == 1
            [order] = trade_calls
            assert not any(
                isinstance(node, (ast.Import, ast.ImportFrom))
                and any(alias.name.split(".")[0] != "time" for alias in node.names)
                for node in ast.walk(tree)
            )
            if ident == 575:
                assert order.func.attr == "Sell" and public["args"] == {"num": 0.1}
                _, opening = header_settings(code)
                assert opening == {"stocks": 10}
                docstring = ast.get_docstring(tree, clean=False)
                assert all(
                    s in docstring
                    for s in ("period: 1d", "basePeriod: 1h", "Bitfinex", "BTC_USD")
                )
            else:
                assert order.func.attr == "Buy" and len(order.args) == 1
                assert public["args"]["maxBidPrice"] == 0
            snippets = [
                {"line": n, "code": line.strip()}
                for n, line in enumerate(code.splitlines(), 1)
                if line.strip() in spec["snippets"]
            ]
            assert len(snippets) == len(spec["snippets"])
            proof = {
                "id": ident,
                "archive": link,
                "publisher_page": spec["publisher"],
                "document_sha256": digest(document),
                "code_sha256": digest(code.encode()),
                "public_settings": public,
                "order_call_types": [order.func.attr],
                "role_evidence": snippets,
            }
            if ident == 575:
                proof["archived_mode"] = {
                    "venue": "Bitfinex",
                    "instrument": "BTC_USD",
                    "period": "1d",
                    "base_period": "1h",
                    "opening_base_units": opening["stocks"],
                }
            results.append(proof)
            coverage.append([ident, spec["status"], spec["reason"]])
    write(
        output,
        {
            "source_revision": FMZ_REF,
            "line_reference": "Extracted Python source block, one-based.",
            "coverage": coverage,
            "evidence": results,
            "results": [],
            "replay_cost_model": {
                "fee_per_side": FEE,
                "additional_execution_adjustment_per_side": EXECUTION,
                "implementation": "research/delta_strategy_replay.py",
                "applied_to_these_dispositions": False,
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    generate(arguments.archive, arguments.work, arguments.output)
