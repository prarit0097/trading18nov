import json
import re
import sys
import traceback
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
mode = sys.argv[1]
try:
    raw = (w / "r41-noro-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    if mode != "literal":
        src, n = re.subn(r"input\((true|false|[0-9]+), defval = \1,", r"input(\1,", src)
        assert n == 11, n
        for typ, var in (
            ("int", "_direction"),
            ("float", "dot"),
            ("float", "uplevel"),
            ("float", "dnlevel"),
            ("float", "lot"),
        ):
            wtn = rf"(?m)^([ ]*){var} = "
            src, n = re.subn(wtn, rf"\g<1>{typ} {var} = na\n\g<1>{var} := ", src)
            assert n == 1, (var, n)
        if mode == "legacy":
            src = (
                src.replace("request.security(", "security(")
                .replace("syminfo.tickerid", "tickerid")
                .replace("syminfo.mintick", "mintick")
            )
        else:
            src = src.replace("//@version=2", "//@version=5")
            src = re.sub(
                r"(?m)^(\w+ = )input\((?=[0-9]+, minval)", r"\1input.int(", src
            )
            for old, new in {
                "change": "ta.change",
                "highest": "ta.highest",
                "lowest": "ta.lowest",
            }.items():
                src = re.sub(rf"\b{old}\(", new + "(", src)
            for c in ("black", "lime", "red", "blue"):
                src = re.sub(rf"\b{c}\b", f"color.{c}", src)
            src = src.replace("'W'", "'W'")
            old = "request.security(syminfo.tickerid, tf, zigzag())"
            statement = "zigzag()[1]" if mode in ("confirmed", "recast") else "zigzag()"
            src = src.replace(
                old,
                f"request.security(syminfo.tickerid, tf, {statement}, lookahead=barmerge.lookahead_on)",
            )
    if mode == "recast":
        old = '    strategy.entry("Short", strategy.short, needshort == false ? 0 : lot, stop = dnlevel - syminfo.mintick)'
        assert src.count(old) == 1
        src = src.replace(
            old,
            '    strategy.exit("Flatten", from_entry="Long", stop = dnlevel - syminfo.mintick)',
        )
    watch = {
        "Zigzag": "zz",
        "Dot": "dot",
        "Up": "uplevel",
        "Down": "dnlevel",
        "Lot": "lot",
        "Position": "strategy.position_size",
    }
    src += "".join(f'\nplot({v},"{k}")' for k, v in watch.items())
    data = json.loads((w / "r41-noro-feeds.json").read_bytes())
    keys = ("time", "open", "high", "low", "close", "volume")

    def candles(rows):
        return [dict(zip(keys, b, strict=True)) for b in rows]

    out = []
    for period, assets in data.items():
        for market, tape in assets.items():
            symbol = "BINANCE:" + market
            props = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "quantityStep": "0.001",
                "minContract": "0.001",
            }
            active = (
                src.replace("mintick", "0.1" if market == "BTCUSDT" else "0.01")
                if mode == "legacy"
                else src
            )
            r = pine.run_script(
                active,
                candles(tape["chart"]),
                chart_symbol=symbol,
                chart_timeframe="1D",
                request_bars={symbol + ":W": candles(tape["weekly"]), "$chart": props},
            )
            out.append(
                {
                    "period": period,
                    "market": market,
                    "executed_source_sha256": sha256(active.encode()).hexdigest(),
                    "diagnostics": r["diagnostics"],
                    "strategy": r["strategy"],
                    "plots": {
                        p["title"]: p["values"]
                        for p in r["plots"]
                        if p.get("title") in watch
                    },
                }
            )
    (w / f"r41-noro-{mode}.json").write_text(
        json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / f"r41-noro-{mode}-error.txt").write_text(
        traceback.format_exc(), encoding="utf8"
    )
    raise
