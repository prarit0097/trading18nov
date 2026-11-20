"""Verify the two independent historical broker blockers for FMZ #388."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import read,sha256,write

PINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
PINER="9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea"
SOURCE="daf13b100e92cbd1b8f1f1c13d6c96f932b153e3ca10c1f938c0835b49ecd007"


def fixtures(work,node):
    pinned=read(work/"388-stacked-fixture.json")
    other=read(node/"388-piner.json")
    assert other["engine"]==PINER
    outputs={}
    for mode,native_prices,alternate_prices in (
        ("shared",[110,110],[110,210]),("distinct",[110,210],[110,210]),
        ("shared_reissue",[200,210],[200,210]),
    ):
        actual=[t["exitPrice"] for t in pinned[mode]["broker"]["trades"]]
        assert actual==native_prices
        alternate=[[t["exitPrice"] for t in other["cases"][f"{mode}_{v}"]] for v in (4,5)]
        assert alternate[0]==alternate[1]==alternate_prices
        outputs[mode]={"native":actual,"piner_both_backends":alternate[0]}
    n=read(work/"388-sibling-native.json")
    p=read(node/"388-sibling-causality.json")
    assert p["engine"]==PINER and n[0]==n[1]
    assert [t["qty"] for t in n[0]]==[-49985,-49977]
    timings=[]
    for case,q in zip(p["cases"],(62.492,37.492),strict=True):
        raw=case["closed"]
        assert [round(t["qty"], 3) for t in raw]==[50,q]
        assert all(t["entryPrice"]==100 and t["entryBar"]==1 for t in raw)
        timings.append({"next_open":case["bars"][1]["open"],"future_close":case["bars"][1]["close"],
                        "sibling_native_base":[49.985,49.977],"sibling_piner_base":[50,q]})
    return {"relative_brackets":outputs,"independent_next_open_sizing":timings}


def historical(work,node):
    manifest=read(work/"1070-inputs.json")
    alternate=read(node/"388-piner-historical.json")
    assert alternate["engine"]==PINER
    scopes=[]
    for case,ref,other,expect in zip(
        read(work/"388-probe.json"),manifest["feeds"],alternate["cases"],
        [(74,74,70,37,.1),(133,131,128,39,.01)],strict=True
    ):
        assert case["market"]==ref["market"]==other["market"]
        assert sha256(work/ref["file"])==ref["sha256"]
        assert "error" in case["archived"] and "error" in case["v4"] and "error" in case["v5"]
        raw,units=[case[k] for k in ("v4_names","v4_lot_units")]
        assert all(raw["plots"][k]==v for k,v in units["plots"].items() if k!="observed size")
        old,new=raw["broker"]["trades"],units["broker"]["trades"]
        expected_raw,expected_unit,expected_piner,expected_grid,tick=expect
        assert len(old)==expected_raw and len(new)==expected_unit
        assert all(t["qty"].is_integer() and abs(t["qty"])>=1 for t in new)
        dust=[t for t in old if abs(t["qty"])<.001-1e-10]
        pairs=zip((t for t in old if abs(t["qty"])>=.001-1e-10),new,strict=True)
        for a,b in pairs:
            assert all(a[k]==b[k] for k in ("id","entryTime","exitTime","entryPrice","exitPrice"))
            assert math.isclose(a["qty"]*1000,b["qty"],abs_tol=1e-8)
            assert math.isclose(a["profit"],b["profit"],abs_tol=1e-8)
        assert len(dust)==expected_raw-expected_unit
        alt=other["result"]["closedTrades"]
        assert len(alt)==expected_piner
        off_grid=[t for t in alt if not math.isclose(t["exitPrice"]/tick,round(t["exitPrice"]/tick),abs_tol=1e-7,rel_tol=0)]
        assert len(off_grid)==expected_grid
        scopes.append({"market":case["market"],"float_native_fragments":len(old),
                       "integer_native_fragments":len(new),"diagnostic_dust":dust,
                       "piner_projected_fragments":len(alt),"piner_off_price_grid":len(off_grid),
                       "piner_first_off_price_grid":off_grid[0],"price_increment":tick,
                       "original_signal_equivalence":"Native whole-contract and base-quantity observations agree.",
                       "piner_script_sha256":other["runner_sha256"]})
    return manifest,scopes


def main(work,node,out):
    assert sha256(work/"source-388.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==PINE
    assert sha256(node/"package/dist/index.js")==PINER
    manifest,scopes=historical(work,node)
    write(out,{"schema":"FMZ #388 stacked relative bracket and sibling equity chronology evidence",
               "source_url":"https://www.fmz.com/strategy/376304",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":PINE,"alternate_engine_sha256":PINER,
               "raw_native_sha256":sha256(work/"388-probe.json"),
               "raw_piner_projection_sha256":sha256(node/"388-piner-historical.json"),
               "input_data":manifest,"fixtures":fixtures(work,node),"evidence":scopes,
               "coverage":[[388,"Pending · stacked bracket and causal percentage sizing",
                            "Integer lots remove two float dust fragments. Pine Compat applies the first entry basis to both relative brackets sharing one ID. Piner uses per-entry targets but changes next-open sibling size with future close and produces off-grid alternative prices."]],
               "results":[]})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
