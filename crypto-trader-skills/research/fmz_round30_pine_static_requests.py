import json
import re
import sys
import traceback
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine_compat = import_module("pine_compat")
src = (w / "round28-ha-source.pine").read_text(encoding="utf8")
src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
boundary = "//plotcandle(o, h, l, c"
assert src.count(boundary) == 1
src = src.split(boundary, 1)[0]
names = ("ec1ft", "ec1ft1", "o", "c")
src += "".join(f'\nplot({name},"{name}")' for name in names)
records = []
try:
    cases = json.loads((w / "round28-ha-feeds.json").read_bytes())
    for period, markets in cases.items():
        for market, data in markets.items():
            if sys.argv[1:] and market not in sys.argv[1:]:
                continue
            chart = data["chart"]
            d = data["daily"]
            symbol = "BINANCE:" + market
            ha_id = json.dumps(
                {"chart": "heikinashi", "symbol": symbol}, separators=(",", ":")
            )
            ha = []
            for t, o, h, l, c, v in d:
                oc = (o + c) / 2 if not ha else (ha[-1][1] + ha[-1][4]) / 2
                cc = (o + h + l + c) / 4
                ha.append([t, oc, max(h, oc, cc), min(l, oc, cc), cc, v])
            fields = ("time", "open", "high", "low", "close", "volume")

            def bars(data, fields=fields):
                return [dict(zip(fields, r, strict=True)) for r in data]

            reports = []
            for mode, ha_data in (("derived", ha), ("substituted for isolation", d)):
                out = pine_compat.run_script(
                    src,
                    bars(chart),
                    chart_symbol=symbol,
                    chart_timeframe="240",
                    request_bars={symbol + ":D": bars(d), ha_id + ":D": bars(ha_data)},
                )
                assert all(
                    r["code"] == "W_LEGACY_SECURITY_LOOKAHEAD"
                    for r in out["diagnostics"]
                )
                assert "strategy" not in out
                reports.append(
                    {
                        "mode": mode,
                        "plots": {
                            p["title"]: p["values"]
                            for p in out["plots"]
                            if p.get("title") in names
                        },
                    }
                )
            a, b = reports
            assert {k: v for k, v in a.items() if k != "mode"} == {
                k: v for k, v in b.items() if k != "mode"
            }
            records.append({"period": period, "market": market, "result": a})
    (
        w / ("round28-ha-requests-" + ("-".join(sys.argv[1:]) or "all") + ".json")
    ).write_text(
        json.dumps(records, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (
        w / ("round28-ha-requests-error-" + ("-".join(sys.argv[1:]) or "all") + ".txt")
    ).write_text(traceback.format_exc(), encoding="utf8")
    raise
