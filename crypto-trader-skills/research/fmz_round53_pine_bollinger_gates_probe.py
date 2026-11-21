"""Magnify the saved current-chart Bollinger context and its static security control."""

import json
import re
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
source = (w / "round47-3747.pine").read_text(encoding="utf8")
data = json.loads((w / "round47-3747-feeds.json").read_bytes())["chart"]
for name, direction in [("Upper", "Long Open"), ("Middle", "Long Close")]:
    pat = (
        "(Crossover"
        + name
        + 'Band = input\\(title="Crossover '
        + name
        + ' Band", defval=)"Not Used"'
    )
    source, n = re.subn(
        pat, lambda m, direction=direction: m[1] + '"' + direction + '"', source
    )
    assert n == 1, n
source, z = re.subn(r"(?ms)^gettickerid\(MACandleType\) =>\n.*?(?=^MA = )", "", source)
assert z == 1
a = "security(gettickerid(MACandleType), res(MAResolution), "
b = "security(syminfo.tickerid, res(MAResolution), "


def inner_slices(src, prefix):
    while prefix in src:
        start = src.index(prefix)
        j = start + len(prefix)
        d = 1
        while d:
            if src[j] == "(":
                d += 1
            if src[j] == ")":
                d -= 1
            j += 1
        src = src[:start] + src[start + len(prefix) : j - 1] + src[j:]
    return src


assert source.count(a) == 4 and source.count(b) == 5
source = inner_slices(inner_slices(source, a), b)
variant = sys.argv[1]
assert variant in ("inline", "static")
if variant == "static":
    for old, new in (
        (
            "MA = ma(MAType, MASource, MAPeriod)",
            'MA = security(syminfo.tickerid, "D", sma(close,20))',
        ),
        (
            "Deviation = UseATRDeviation ? atr(ATRPeriod) :  stdev(MASource, MAPeriod)",
            'Deviation = security(syminfo.tickerid, "D", stdev(close,20))',
        ),
        (
            "PercentB = (close - LowerBand)",
            'PercentB = (security(syminfo.tickerid, "D", close) - LowerBand)',
        ),
    ):
        assert source.count(old) == 1, old
        source = source.replace(old, new)
source += '\nplot(longOpen,"Open")\nplot(longClose,"Close")\nplot(strategy.position_size,"Pos")\nplot(strategy.equity,"Eq")'
out = []
for tag, m in data.items():
    for c, bars in m.items():
        keys = ("time", "open", "high", "low", "close", "volume")
        chart = [dict(zip(keys, b, strict=True)) for b in bars]
        ticker = "BINANCE:" + c + "USDT"
        options = {
            "$chart": {
                "minMove": 1,
                "priceScale": 10 if c == "BTC" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "quantityStep": "0.001",
                "minContract": "0.001",
            },
            ticker + ":1D": chart,
            ticker + ":D": chart,
        }
        r = pine.run_script(
            source,
            chart,
            chart_symbol=ticker,
            chart_timeframe="1D",
            request_bars=options,
        )
        out.append(
            [
                tag,
                c,
                r["diagnostics"],
                r["strategy"],
                r["plots"],
                sha256(source.encode()).hexdigest(),
            ]
        )
(w / f"round47-3747-{variant}.json").write_text(
    json.dumps(out, separators=(",", ":")), encoding="utf8"
)
