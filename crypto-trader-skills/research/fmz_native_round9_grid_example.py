"""Stage the published example launcher for an FMZ spot-grid template."""

import argparse
import ast
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_native_round5 import replace_once
from research.fmz_native_round6_audit import ROOT, digest
from research.fmz_native_round7 import display_settings, file_opening, finish, source

IDENT = 941
STEM = "round9-grid-example-account"
WORKER = "fmz_native_round9_grid_example_account_worker.py"


def stage(archive, public, target):
    item = next(
        r
        for r in read(ROOT / "remaining-backtest-round7-coverage.json")["disposition"]
        if r["id"] == IDENT
    )
    with ZipFile(archive) as pin:
        raw, original = source(pin, item["source"])
    assert digest(raw) == item["pinned_document_sha256"]
    settings = display_settings(public, IDENT, original)
    assert not settings["args"]
    launcher = ast.get_docstring(ast.parse(original), clean=False)
    assert "def main():" in launcher and "ext.SpotGridStra(" in launcher
    launcher = replace_once(launcher, "exchanges[1]", "exchange")
    launcher = replace_once(launcher, "'BNB'", "STUDY_BASE")
    code = original + "\n" + launcher
    ast.parse(code)
    jobs = []
    for benchmark in read(target / "round5-native-python-jobs.json"):
        if benchmark["item"]["id"] != 1107:
            continue
        feed = benchmark["feed"]
        jobs.append(
            {
                "item": {
                    "id": IDENT,
                    "name": item["name"],
                    "source": item["source"],
                    "source_sha256": digest(raw),
                    "code": code,
                    "args": {"STUDY_BASE": feed["coin"]},
                },
                "feed": feed,
                "options": {"opening": file_opening(target, feed, {}, IDENT)},
                "public": {
                    **settings,
                    "launcher_sha256": digest(launcher.encode()),
                    "balance_schema": "https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/ws-api/account",
                },
                "note": "Run the source package through its published BNB example launcher. Use the supplied BTC or ETH Binance tape and reconstruct the requested Binance balance shape from the local native ledger's free and locked balances. Preserve its 3% grid, 50% balance point, precision, minimum quantity and decision intervals.",
            }
        )
    assert len(jobs) == 4
    base = (target / "fmz_native_python_round7_worker.py").read_text(encoding="utf-8")
    code_marker = '        runtime["print"] = lambda *args, **kwargs: None\n'
    worker = replace_once(
        base, code_marker, code_marker + '        runtime["ext"] = SimpleNamespace()\n'
    )
    venue_marker = '        venue = runtime["exchange"]\n'
    worker = replace_once(
        worker,
        venue_marker,
        venue_marker
        + """        original_account = venue.GetAccount

        def spot_account():
            account = original_account()
            balances = []
            for asset, free, locked in (
                (feed["coin"], "Stocks", "FrozenStocks"),
                ("USDT", "Balance", "FrozenBalance"),
            ):
                assert 0 <= account[free] and 0 <= account[locked]
                balances.append(dict(asset=asset, free=str(account[free]), locked=str(account[locked])))
            account["Info"] = {"balances": balances}
            return account

        venue.GetAccount = spot_account
""",
    )
    worker = worker.replace("round7-native-python-", STEM + "-")
    ast.parse(worker)
    (target / WORKER).write_text(worker, encoding="utf-8", newline="\n")
    write(target / (STEM + "-jobs.json"), jobs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("public_cache", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--finish", type=Path)
    args = parser.parse_args()
    if args.finish:
        finish(args.target, args.finish, stem=STEM, worker=WORKER)
    else:
        stage(args.archive, args.public_cache, args.target)
