"""Recover #4762 as JavaScript and identify its historical contract dependencies."""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

from research.fmz_native_round6_replay import public_settings
from research.fmz_round7_magnifier import sha256, write

SOURCE = "fc2225faba6f0edda82124c2553d88f1fb0521e9c49f5232c5524b35f19938b3"
PAGE = "83af8462b0ab189823f5a0d654e893c3c4d863a1688b94b97fd5ebbad29fd037"
ORIGIN = "https://www.fmz.com/strategy/3648"


def main(document, publisher, source_only, runtime, output):
    assert sha256(document) == SOURCE and sha256(publisher) == PAGE
    archive = document.read_text(encoding="utf-8")
    assert "796期货反手加倍算法" in archive and ORIGIN in archive
    fence = chr(96) * 3
    (body,) = re.findall(
        r"(?ms)^" + fence + r" javascript[^\n]*\n(.*?)^" + fence, archive
    )
    settings = public_settings(publisher, {"code": body, "parameter_page": ORIGIN})
    assert settings["args"]["Symbol"] == "this_week"
    assert settings["args"]["MarginLevel"] == 10 and settings["args"]["OpAmount"] == 1
    assert settings["args"]["Interval"] == 1
    role = {
        "market": (
            "exchange.SetContractType(Symbol)",
            "exchange.SetMarginLevel(MarginLevel)",
            "e.GetTicker",
        ),
        "inventory": ("e.GetPosition", "e.GetAccount", "account.Stocks * MarginLevel"),
        "order_management": ("e.GetOrders", "e.CancelOrder", "e.Buy", "e.Sell"),
    }
    assert all(piece in body for values in role.values() for piece in values)
    assert not re.search(r"(?mi)^\s*(start|end|period|basePeriod|exchanges)\s*:", body)
    source_only.write_bytes(body.encode("utf-8"))
    checked = subprocess.run(
        [str(runtime), "--check", str(source_only)], capture_output=True, check=True
    )
    assert not checked.stdout and not checked.stderr
    version = subprocess.check_output([str(runtime), "--version"], text=True).strip()
    write(
        output,
        {
            "schema": "FMZ #4762 JavaScript source recovery and contract identity",
            "source_sha256": SOURCE,
            "program_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "publisher_settings": settings,
            "publisher_annotation": "https://www.fmz.com/digest-topic/6215",
            "syntax_check": {"runtime": version, "exit_code": checked.returncode},
            "source_dependencies": role,
            "notes": {
                "classification": "Archive and publisher show a standalone JavaScript strategy. It parses without changes. The original title specifies the 796 futures exchange. A separate FMZ annotation confirms coin collateral and fractional quantities.",
                "binding": "The authored this_week value is a rolling selector. The archived document identifies no dated contract, run window or price tape.",
                "execution": "The program reads bid/ask, account and position state during each leveraged order cycle. Summary candles cannot establish fill or cancellation timing. No matched 796 weekly tape is available in the workspace.",
            },
            "coverage": [
                [
                    4762,
                    "Pending · 796 weekly futures contract and recorded book",
                    "Recovered and syntax-checked the complete JavaScript strategy. The publisher binds a rolling this_week selector and 10x setting, but the archive lacks the dated 796 contract and matched historical book and settlement data.",
                ]
            ],
            "results": [],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
