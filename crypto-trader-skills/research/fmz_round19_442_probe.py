"""Run literal #442 v2 and a weekday-preserving v5 lower-base control."""

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, near, pine_compat, sha256

SOURCE_SHA = "8f4d081f51bef7d668f0177dec6bea86c430c9a015dce1d5fc6657aa316b6a2f"
DAY = 86_400_000
M15 = 900_000
M30 = M15 * 2
CAPITAL = 100_000
OBS = """
plot(DIPlus, title="Verified DMI plus")
plot(DIMinus, title="Verified DMI minus")
plot(istradingsession ? 1 : 0, title="Verified session")
plot(buy_signal ? 1 : 0, title="Verified long")
plot(sel_signal ? 1 : 0, title="Verified short")
"""


def scripts():
    raw = (ROOT / "source-442.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (code,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    archive, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", code)
    assert n == 1
    contemporary = archive
    changes = (
        ("//@version=2", "//@version=5", 1),
        ("conversionPeriods = input(", "conversionPeriods = input.int(", 1),
        ("defval=7, minval=1),", "defval=7, minval=1)", 1),
        ("avg(", "math.avg(", 2),
        ("lowest(", "ta.lowest(", 1),
        ("highest(", "ta.highest(", 1),
        ("max(", "math.max(", 4),
        ("abs(", "math.abs(", 3),
        ("sma(DX, len)", "ta.sma(DX, len)", 1),
        ("color=blue", "color=color.blue", 3),
        ("?gray:na", "?color.gray:na", 1),
        (
            "input(title='Use Trading Session?', type=bool, defval=true)",
            "input.bool(title='Use Trading Session?', defval=true)",
            1,
        ),
        (
            "input(title='Trade Session:', defval='0400-1500', confirm=false)",
            "input.session(title='Trade Session:', defval='0400-1500:23456', confirm=false)",
            1,
        ),
        (
            "strategy.order('buy', long=true,",
            "strategy.order('buy', direction=strategy.long,",
            1,
        ),
        (
            "strategy.order('sel', long=false,",
            "strategy.order('sel', direction=strategy.short,",
            1,
        ),
    )
    for old, new, count in changes:
        assert contemporary.count(old) == count, (old, count)
        contemporary = contemporary.replace(old, new)
    for name in (
        "SmoothedTrueRange",
        "SmoothedDirectionalMovementPlus",
        "SmoothedDirectionalMovementMinus",
    ):
        old = f"{name} = nz({name}[1])"
        assert contemporary.count(old) == 1
        contemporary = contemporary.replace(
            old, f"{name} = 0.0\n{name} := nz({name}[1])"
        )
    active = "currency=currency.USD)"
    assert contemporary.count(active) == 1
    magnified = contemporary.replace(
        active, "currency=currency.USD, use_bar_magnifier=true)"
    )
    return archive, contemporary, magnified


def cases():
    reference = json.loads((ROOT / "442-inputs.json").read_bytes())
    data = (ROOT / reference["fx"]["file"]).read_bytes()
    assert sha256(data) == reference["fx"]["sha256"]
    assert (
        sha256(data)
        == "50eedc75d25d24e7ad24ca953e9bd5032b70b5b20d1fcb20e8d6cd9df3524ef2"
    )
    fx = json.loads(data)
    pairs = fx["pairs"][0]
    assert pairs["from"] == "USDT" and pairs["to"] == "USD"
    dates = {x["effectiveTime"]: x["rate"] for x in pairs["rates"]}
    for item in reference["records"]:
        raw = (ROOT / item["file"]).read_bytes()
        assert sha256(raw) == item["sha256"]
        payload = json.loads(raw)
        keys = ("time", "open", "high", "low", "close", "volume")
        chart = [dict(zip(keys, row, strict=True)) for row in payload["chart"]]
        base = [dict(zip(keys, row, strict=True)) for row in payload["base"]]
        start, stop = payload["start"], payload["stop"]
        assert list(dates) == list(range(start, stop, DAY))
        assert [r["time"] for r in chart] == list(range(start, stop, M30))
        assert [r["time"] for r in base] == list(range(start, stop, M15))
        groups = [
            {"chartBarIndex": i, "bars": base[2 * i : 2 * i + 2]}
            for i in range(len(chart))
        ]
        for parent, pair in zip(chart, groups, strict=True):
            a, b = pair["bars"]
            assert parent["open"] == a["open"] and parent["close"] == b["close"]
            assert parent["high"] == max(a["high"], b["high"])
            assert parent["low"] == min(a["low"], b["low"])
            near(parent["volume"], math.fsum((a["volume"], b["volume"])))
        opts = {**engine_options(item["market"]), "chart_timeframe": "30"}
        opts["request_bars"]["$currencyRates"] = fx
        yield item, start, stop, chart, groups, dates, opts


def run():
    archived, migrated, base = scripts()
    bundle = []
    for sample, start, stop, chart, groups, _, opts in cases():
        outcomes = [
            pine_compat.run_script(archived, chart, **opts),
            pine_compat.run_script(migrated, chart, **opts),
            pine_compat.run_script(
                base + OBS,
                chart,
                magnifier_bars={"schemaVersion": 1, "chartBars": groups},
                **opts,
            ),
        ]
        bundle.append(
            {
                **sample,
                "start": start,
                "end": stop,
                "original": outcomes[0],
                "migrated": outcomes[1],
                "base": outcomes[2],
            }
        )
    (ROOT / "442-replay.json").write_text(
        json.dumps(bundle, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "442-replay-error.txt").write_text(
            traceback.format_exc(), encoding="utf8"
        )
        raise
