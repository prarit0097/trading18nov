import json
import re
import sys
import traceback
from hashlib import sha256
from importlib import import_module
from pathlib import Path

pc = Path(__file__).parent
sys.path.insert(0, str(pc / "priced-runtime"))
p = import_module("pine_compat")
try:
    source = (pc / "r35-bbe-source.pine").read_text(encoding="utf8")
    source = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    marker = '// strategy(title="[EURUSD60] BB Expansion Strategy", shorttitle="[EURUSD60] BBEXP",overlay=true, max_bars_back=5000, max_labels_count=500)'
    assert source.count(marker) == 1
    source = source.replace(
        marker,
        marker[3:-1]
        + ",initial_capital=1000000,commission_type=strategy.commission.percent,commission_value=0.059)",
    )
    projected = bool(sys.argv[1:])
    if projected:
        found = (
            "base=security(syminfo.tickerid, resFirstTime, ema(close[index],emaLen))"
        )
        other = "sig=security(syminfo.tickerid, resFirstTime, ema(base[index],smooth))"
        assert source.count(found) == source.count(other) == 1
        source = source.replace(found, 'base=security("CONTEXT:BASE","60",close)')
        source = source.replace(other, 'sig=security("CONTEXT:SIGNAL","60",close)')
    items = {
        "Big mean": "lrgBbBasis",
        "Small mean": "smlBbBasis",
        "BB eligible": "isBbEntry?1:0",
        "Trend base": "base",
        "Trend signal": "sig",
        "Buy": "(isBbLong and isEmaLong)?1:0",
        "Sell": "(isBbShort and isEmaShort)?1:0",
        "Stop long": "stopLossLineForLong",
        "Stop short": "stopLossLineForShort",
        "Target long": "takeProfitLineForLong",
        "Target short": "takeProfitLineForShort",
        "Exit long": "(isAtrLongStop or isAtrLongLimit)?1:0",
        "Exit short": "(isAtrShortStop or isAtrShortLimit)?1:0",
        "Position": "strategy.position_size",
    }
    source += "".join(f'\nplot({expr},"{name}")' for name, expr in items.items())
    cases = []
    for label, markets in json.loads((pc / "r35-bbe-feeds.json").read_bytes()).items():
        for m, d in markets.items():
            cols = ("time", "open", "high", "low", "close", "volume")
            chart = [dict(zip(cols, r, strict=True)) for r in d["chart"]]
            ref = [dict(zip(cols, r, strict=True)) for r in d["ref"]]
            sym = "BINANCE:" + m
            props = {
                "minMove": 1,
                "priceScale": 10 if m == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
            }
            req = {sym + ":60": chart, sym + ":240": ref, "$chart": props}
            if projected:
                calc = """//@version=4
study("Confirmed 4h recurrence")
chosenEma(feed,len) =>
    w=2.0/(len+1)
    state=0.0
    state := na(state[1]) ? feed : feed*w+(1-w)*state[1]
x=chosenEma(close,14)
y=chosenEma(x,3)
plot(x,"base")
plot(y,"signal")
"""
                proof = p.run_script(calc, ref, chart_symbol=sym, chart_timeframe="240")
                assert not proof["diagnostics"]
                channels = {z["title"]: z["values"] for z in proof["plots"]}
                for v in ("base", "signal"):
                    out = []
                    for i, rec in enumerate(chart):
                        selected = (i + 1) // 4 - 1
                        if selected >= 0:
                            price = channels[v][selected]
                            out.append(
                                {
                                    "time": rec["time"],
                                    "open": price,
                                    "high": price,
                                    "low": price,
                                    "close": price,
                                    "volume": 1,
                                }
                            )
                    req[f"CONTEXT:{v.upper()}:60"] = out
            z = p.run_script(
                source, chart, chart_symbol=sym, chart_timeframe="60", request_bars=req
            )
            cases.append(
                {
                    "period": label,
                    "market": m,
                    "diagnostics": z["diagnostics"],
                    "strategy": z["strategy"],
                    "executed_source_sha256": sha256(source.encode()).hexdigest(),
                    "plots": {
                        x["title"]: x["values"]
                        for x in z["plots"]
                        if x.get("title") in items
                    },
                }
            )
    (
        pc / ("r35-bbe-firstseed.json" if sys.argv[1:] else "r35-bbe-native.json")
    ).write_text(
        json.dumps(cases, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (pc / "r35-bbe-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    raise
