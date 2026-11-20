"""Test numeric entry direction against the pinned native legacy Pine backend."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

LITERALS = ("100", "1", "0", "true", "false", "strategy.long", "strategy.short")


def run(runtime, output):
    sys.path.insert(0, str(runtime))
    from pine_compat import pine_compat

    bars = [
        {
            "time": 1_704_067_200_000 + 86_400_000 * i,
            "open": 100 + i,
            "high": 102 + i,
            "low": 99 + i,
            "close": 100 + i,
            "volume": 5,
        }
        for i in range(4)
    ]
    results = {}
    for direction in LITERALS:
        source = (
            '//@version=4\nstrategy("Direction fixture")\n'
            f'if bar_index == 0\n    strategy.entry("Witness",{direction})\n'
            "plot(strategy.position_size)\n"
        )
        result = pine_compat.run_script(source, bars)
        assert not result["diagnostics"]
        (position,) = [plot["values"] for plot in result["plots"]]
        results[direction] = position
    build = Path(pine_compat.__file__)
    document = {
        "runtime_sha256": hashlib.sha256(build.read_bytes()).hexdigest(),
        "direction_witnesses": results,
    }
    output.write_text(
        json.dumps(document, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.runtime, args.output)


if __name__ == "__main__":
    main()
