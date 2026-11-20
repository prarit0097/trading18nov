"""Extract the complete Kraken USDTGBP daily closes used by #5006."""

import json
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import sha256

DAY = 86_400_000
START = 1_785_542_400_000
END = 1_793_491_200_000


def stage(raw, output):
    answer = json.loads(raw.read_bytes())
    assert answer["error"] == []
    rates = []
    for timestamp, start, high, low, close, vwap, volume, number in answer["result"][
        "USDTGBP"
    ]:
        effective = timestamp * 1000 + DAY
        if effective < START or effective > END:
            continue
        assert timestamp % 86_400 == 0 and number > 0 and Decimal(volume) > 0
        assert Decimal(0) < Decimal(low) <= Decimal(close) <= Decimal(high)
        assert Decimal(low) <= Decimal(start) <= Decimal(high)
        assert Decimal(low) <= Decimal(vwap) <= Decimal(high)
        rates.append([effective, close])
    assert [row[0] for row in rates] == list(range(START, END + DAY, DAY))
    output.write_text(
        json.dumps(rates, separators=(",", ":"), allow_nan=False), encoding="ascii"
    )
    print(f"{len(rates)} completed-day rates with SHA-256 {sha256(output)}")


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
