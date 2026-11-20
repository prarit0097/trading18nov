import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

OBSERVATIONS = """
plot(L_second_condt and testPeriod and ACT_BT ? 1 : 0, title="observed L")
plot(S_second_condt and testPeriod and ACT_BT ? 1 : 0, title="observed S")
plot(close * tp_ / syminfo.mintick, title="observed profit ticks")
plot(close * sl_ / syminfo.mintick, title="observed loss ticks")
plot(strategy.position_size, title="observed position")
plot(src0, title="observed request")
plot(weight, title="observed timestamps")
"""

def main():
    archive = (ROOT/"source-356.md").read_bytes()
    assert sha256(archive) == "29cd57977b69a28a1b96dbc0ce3e3d8d36b1d2ff7f7399853eea2a3eed1821e7"
    fence = chr(96)*3
    source, = re.findall(r"(?ms)^"+fence+r"[^\n]*\n(.*?)^"+fence, archive.decode())
    assert not re.search(r"(?m)^//@version", source)
    output = []
    for market in ("BTCUSDT","ETHUSDT"):
        data = json.loads((ROOT/f"1070-{market}.json").read_bytes())
        bars = objects(data["chart"])
        opts = {**engine_options(market), "chart_timeframe": "30"}
        opts["request_bars"][opts["chart_symbol"]+":30"] = bars
        row = {"market": market}
        for label, src in {
            "archived": source,
            "v4_legacy": "//@version=4\n"+source,
            "v4_explicit": "//@version=4\n" + re.sub(r'(strategy\.entry\("L"\s*,)1,', r'\1strategy.long,',
                re.sub(r'(strategy\.entry\("S"\s*,)0,', r'\1strategy.short,', source)),
        }.items():
            try:
                result = pine_compat.run_script(src + OBSERVATIONS, bars, **opts)
                row[label] = {"broker": result["strategy"], "diagnostics": result["diagnostics"],
                              "plots": {p["title"]: p["values"] for p in result["plots"] if p.get("title","").startswith("observed ")}}
            except ValueError as error:
                row[label] = {"exception": str(error).splitlines()}
        output.append(row)
    (ROOT/"356-probe.json").write_bytes(json.dumps(output,separators=(",",":"),allow_nan=False).encode())

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"356-probe-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
