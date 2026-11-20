"""Emit the verified archived-v2 zero-trade result for #3805."""

import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "9b2d58f0863e272c09f52db1026c0768aa26bce0ab307dbe055231434781bf1b"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000


def finalize(work, output):
    proof = work / "3805-verified.json"
    controls = read(proof)
    data = read(work / "3805-inputs.json")
    assert sha256(work / "source-3805.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(x[0] == "PermissionError" for x in isolation.values())
    cases = controls["cases"]
    assert [c["market"] for c in cases] == ["BTCUSDT", "ETHUSDT"]
    for row, ref, diagnostic in zip(cases, data["feeds"], (5, 3), strict=True):
        assert row["file"] == ref["file"] and row["market"] == ref["market"]
        assert sha256(work / row["file"]) == row["sha256"] == ref["sha256"]
        assert row["zero_signals_and_orders"] and row["capital"] == CAPITAL
        assert row["equity_rows_verified"] == row["chart_bars"] == 371
        assert row["base_bars"] == 8904
        assert row["altered_coefficients_diagnostic_orders"] == diagnostic
    attrs = {
        "id": 3805,
        "group": "FMZ · Pine v2 integer-coefficient adaptive trend",
        "exit": "Opposite market signal, no signals in the archived replay",
        "period": f"Binance USD-M · {iso_day(cases[0]['start'])} to {iso_day(cases[0]['end'])} UTC exclusive",
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
    }
    report = {
        "schema": "FMZ 3805 archived v2 integer division and zero-order proof",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_url": "https://www.fmz.com/strategy/440714",
        "source_sha256": SOURCE,
        "engine_sha256": ENGINE,
        "verified_sha256": sha256(proof),
        "input_data": data,
        "isolation": isolation,
        "model": {
            "source": "Saved Pine v2 default scope. The newer security namespace occurs twice on visualization-only fractals. With the archived current-timeframe default, both expressions evaluate their own local fractal series and preserve every active trading statement.",
            "proof": "The two fast and two slow processing constants all divide two integers and equal zero. A zero seed and a zero multiplier leave both adaptive averages identically zero. Their strict greater/less comparisons therefore cannot signal. All 742 candles and marks exhibit zero orders and executions. Starting cash stays 1,000,000 USDT per market.",
            "sensitivity": "The diagnostic intentionally changes twelve numerator literals to 2.0 in the two KAMA and two fractal smoothing calculations. This gives 5 BTC and 3 ETH order events. Those edited-parameter routes do not supply performance rows. The exact historical FMZ host's numeric promotion for these inputs is unconfirmed; the named benchmark uses Pine v2 compatibility and documented historical integer division.",
        },
        "coverage": [[
            3805,
            "Tested · Pine v2 integer-coefficient gate · no trades",
            "Complete 371 BTC and 371 ETH daily chart samples and primary hourly archives. Both adaptive series are provably zero with the archived Pine v2 integer operands, closing every potential decision path. The separate float edit changes results and is excluded from metrics.",
        ]],
        "results": [
            {**attrs, "market": label, **ledger_metrics([], capital, 0)}
            for label, capital in (("BTCUSDT", CAPITAL), ("ETHUSDT", CAPITAL), ("BTCUSDT + ETHUSDT", CAPITAL * 2))
        ],
        **controls,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
