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
    raw = (w / "r44-drexel-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    if mode != "literal":
        src = src.replace("request.security(", "security(").replace(
            "syminfo.tickerid", "tickerid"
        )
        groups = {
            "jma(src,length) =>": ("tmp0", "tmp1", "tmp3", "tmp4"),
            "rsx(src,length) =>": (
                "f90_",
                "f88",
                "f28",
                "f30",
                "f38",
                "f40",
                "f48",
                "f50",
                "f58",
                "f60",
                "f68",
                "f70",
                "f78",
                "f80",
            ),
        }
        for header, variables in groups.items():
            assert src.count(header) == 1
            prefix = "".join(f"\n    float {var} = na" for var in variables)
            for var in variables:
                old = rf"(?m)^    {var}\s*=\s*"
                src, n = re.subn(old, f"    {var} := ", src)
                assert n == 1, (var, n)
            src = src.replace(header, header + prefix)
        old = "c3a = nz(c3a[1])"
        assert src.count(old) == 1
        src = src.replace(old, "float c3a = na\nc3a := nz(c3a[1])")
    if mode in ("projected", "available"):
        for name, variant in (("trend", "high"), ("trend2", "high"), ("trend3", "low")):
            src, n = re.subn(rf"(?m)^{name} = .*$", f"{name} = {variant}", src)
            assert n == 1
    if mode in ("confirmed", "available"):
        for name in ("trend", "trend2", "trend3"):
            old = f"security(tickerid,'D',{name})"
            assert src.count(old) == 1
            src = src.replace(old, f"security(tickerid,'D',{name}[1])")
    watch = {
        "c3a": "c3a",
        "Derived trend": "trend1",
        "Daily high": "bh1",
        "Daily low": "bh2",
        "Trend long low": "Trend33",
        "Trend short high": "Trend11",
        "Long": "x1?1:0",
        "Short": "y1?1:0",
        "Position": "strategy.position_size",
    }
    if mode == "prefix":
        src = src.split("bc=security(")[0]
        watch = {
            "c3a": "c3a",
            "Derived trend": "trend1",
            "High branch 1": "trend",
            "High branch 2": "trend2",
            "Low branch": "trend3",
        }
    src += "".join(f'\nplot({value},"{label}")' for label, value in watch.items())
    packages = json.loads((w / "r44-drexel-feeds.json").read_bytes())
    keys = ("time", "open", "high", "low", "close", "volume")

    def items(rows):
        return [dict(zip(keys, r, strict=True)) for r in rows]

    out = []
    for period, assets in packages.items():
        for market, tape in assets.items():
            prop = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "minContract": "0.001",
                "quantityStep": "0.001",
            }
            symbol = "BINANCE:" + market
            context = {
                symbol + ":" + ("D" if k == "1440" else k): items(v)
                for k, v in tape["contexts"].items()
            }
            context["$chart"] = prop
            streams = (
                tape["contexts"].items()
                if mode == "prefix"
                else [("240", tape["chart"])]
            )
            for frame, bars in streams:
                witness_bars = bars[:48] if mode == "prefix" else bars
                r = pine.run_script(
                    src,
                    items(witness_bars),
                    chart_symbol=symbol,
                    chart_timeframe="D" if frame == "1440" else frame,
                    request_bars=context,
                )
                out.append(
                    {
                        "period": period,
                        "market": market,
                        "frame": frame,
                        "executed_source_sha256": sha256(src.encode()).hexdigest(),
                        "diagnostics": r["diagnostics"],
                        "strategy": r["strategy"],
                        "plots": {
                            p["title"]: p["values"]
                            for p in r["plots"]
                            if p.get("title") in watch
                        },
                    }
                )
    (w / f"r44-drexel-{mode}.json").write_text(
        json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / f"r44-drexel-{mode}-error.txt").write_text(
        traceback.format_exc(), encoding="utf8"
    )
    raise
