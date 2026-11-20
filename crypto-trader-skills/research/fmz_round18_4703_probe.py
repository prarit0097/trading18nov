"""Probe literal archived #4703 on the saved daily Binance market range."""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, pine_compat, sha256

SOURCE = "ee96c4e55874f22138b783482d1c5213122014fd1f133fceea83403c6b5e6d27"
FEEDS = {
    "BTCUSDT": "a7acbcdedcbdc3da6d72bfd9a6f3a8fbfebaffaf47b264778b4dae4b44bb1640",
    "ETHUSDT": "b9affb20b5e749f7b27232edb0d256b69c89e2c4e6f9f52911f1c438f36b9c65",
}
DAY = 86_400_000
OBSERVE = """
plot(PrevDayHigh, title="Verified prior high")
plot(PrevDayLow, title="Verified prior low")
plot(PrevDayClose, title="Verified prior close")
plot(tradeEventPrice, title="Verified pivot")
plot(mxloss, title="Verified stop distance")
"""


def stamp(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp()) * 1000


def inputs():
    raw = (ROOT / "source-4703.md").read_bytes()
    assert sha256(raw) == SOURCE
    (code,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", code)
    assert n == 1
    return code


def candles(market):
    raw = (ROOT / f"5411-feed-{market}.json").read_bytes()
    assert sha256(raw) == FEEDS[market]
    start, stop = map(stamp, ("2022-11-30", "2023-12-06"))
    rows = [row for row in json.loads(raw) if start <= row[0] < stop]
    assert [r[0] for r in rows] == list(range(start, stop, DAY))
    keys = ("time", "open", "high", "low", "close", "volume")
    return [dict(zip(keys, r, strict=True)) for r in rows], stop


def run():
    receipts = []
    source = inputs()
    for market in FEEDS:
        chart, clock = candles(market)
        opts = {
            **engine_options(market),
            "chart_timeframe": "D",
            "execution_times": [clock] * len(chart),
        }
        receipt = {"market": market, "chart_bars": len(chart), "clock": clock}
        for label, program in (("authored", source), ("observed", source + OBSERVE)):
            try:
                receipt[label] = pine_compat.run_script(program, chart, **opts)
            except ValueError as error:
                receipt[label] = {"compile_or_host_error": str(error).splitlines()}
        receipts.append(receipt)
    (ROOT / "4703-probe.json").write_text(
        json.dumps(receipts, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "4703-error.txt").write_text(traceback.format_exc(), encoding="utf8")
        raise
