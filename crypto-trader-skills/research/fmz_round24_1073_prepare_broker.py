"""Reuse the audited #2994 fixed-cash Piner broker for the equivalent #1073 source."""

import hashlib
import sys
from pathlib import Path

PINNED = "35c2456dad1719fc90680391133b82d2927bebcc8dbd9552e70d318af500cef4"


def prepare(original, output):
    body = original.read_bytes()
    assert hashlib.sha256(body).hexdigest() == PINNED
    runner = body.decode("utf-8")
    changes = (
        ('run(script, bars, market)', 'run(script, bars, market, timeframe = "D")'),
        ('timeframe: "D", mintick:', 'timeframe, mintick:'),
        ('"source-2994.md"', '"source-1073.md"'),
        ('f9ccc275870a1bd0cb3dab7160fe0a46fa4c719c07aeb139798aeb28baf7c265', '50de3085564b9c1ab144405b1d6f4af89ee4efff64845a3227dd50c63154fa71'),
        ('line.startsWith("strategy(title=\'VMC\'"));', 'line.startsWith("//strategy(title=\'VMC\'")).slice(2);'),
        ('"2994-replay.json"', '"1073-replay.json"'),
        ('payload.day.map(', 'payload.chart.map('),
        ('run(replay, chart, market);', 'run(replay, chart, market, "120");'),
        ('"2994-piner.json"', '"1073-piner.json"'),
    )
    for old, new in changes:
        assert runner.count(old) == 1, old
        runner = runner.replace(old, new)
    output.write_bytes(runner.encode("utf-8"))


if __name__ == "__main__":
    prepare(*map(Path, sys.argv[1:]))
