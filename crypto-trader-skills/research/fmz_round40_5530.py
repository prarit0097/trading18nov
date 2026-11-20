"""Confirm the #5530 Boolean operand and missing-series broker discrepancies."""

import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, read, sha256, write

SOURCE="5c125dea008e6af98abbb053d77d3da81f93e9ba5ff5a6492a7816e2455d522a"
NATIVE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
PINER="9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea"


def market(name, chart, native):
    assert len(chart) == 371
    original = native["literal"]["errors"]
    assert original[0].startswith("E_LEGACY_VERSION_FEATURE")
    after_spellings = native["literal_version_vocabulary"]["errors"]
    assert len(after_spellings) == 2
    assert all("ta.crossunder" in e and "source2" in e and "got series bool" in e for e in after_spellings)
    variants = ("boolean_numeric_control", "minus_point_eight_control")
    numeric, threshold = [native[f"{v}_version_vocabulary"] for v in variants]
    for label, run in zip(variants, (numeric,threshold), strict=True):
        assert not run["diagnostics"]
        assert run == native[f"{label}_daily_alias_version_vocabulary"]
    common = ["scope value","scope buy"]
    assert all(numeric["plots"][k] == threshold["plots"][k] for k in common)
    different = [(i,iso_day(chart[i][0]),a,b) for i,(a,b) in enumerate(
        zip(numeric["plots"]["scope sell"],threshold["plots"]["scope sell"],strict=True)) if a != b]
    order_counts = [len(r["orders"]) for r in (numeric,threshold)]
    assert (different, order_counts) == (([],[68,68]) if name=="BTCUSDT" else
                                          ([(19,"2022-12-03",1,0)],[78,76]))
    return {"market":name,"daily_bars":len(chart),"literal_first_error":original[0],
            "normalized_vocabulary_errors":after_spellings,"diagnostic_sell_gate_differences":different,
            "numeric_control_entry_order_counts":order_counts}


def alternate(piner):
    out = read(piner/"5530-piner.json")
    assert out["engine"] == PINER
    cases = out["results"]
    assert "undefined variable" in cases["literal"]["compileException"]
    for name, case in cases.items():
        if name == "literal":
            continue
        assert not case["diagnostics"]
        traces=case["traces"]
        assert traces["backendAgreement"] and traces["js"] == traces["interp"]
        case=traces["js"]
        assert case["frames"] == 371
        if name in ("vocabulary", "vocabularyBound", "guard_script"):
            assert [p["defined"] for p in case["plotted"]] == [0,371,371]
            assert [p["ones"] for p in case["plotted"][1:]] == [0,0]
        assert case["trades"] == (739 if name in ("vocabulary","vocabularyBound") else 0)
    return cases


def main(work,piner,out):
    assert sha256(work/"source-5530.md") == SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd") == NATIVE
    assert sha256(piner/"package/dist/index.js") == PINER
    isolation = read(work/"round3-isolation-python.json")
    assert set(isolation) == {"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    assert read(piner/"isolation-probe.json") == {"privateDenied":True,"networkDenied":True}
    feed, probe=work/"5530-feed.json",work/"5530-native.json"
    data, native=read(feed),read(probe)
    assert len(data["receipts"]) == 26
    rows = [market(m, chart, native[m]) for m,chart in data["markets"].items()]
    write(out,{"schema":"FMZ #5530 crossunder Boolean operand and unreachable entry evidence",
               "source_url":"https://www.fmz.com/strategy/432783",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"native_engine_sha256":NATIVE,"piner_engine_sha256":PINER,
               "input_sha256":sha256(feed),"native_sha256":sha256(probe),
               "piner_sha256":sha256(piner/"5530-piner.json"),"market_receipts":data["receipts"],
               "markets":rows,"alternate":alternate(piner),
               "coverage":[[5530,"Pending · Boolean crossunder operand",
                            "Vocabulary-only v4 repair leaves two numeric operand errors. Replacing the Boolean with either 1/0 or −0.8 changes an actual ETH signal. Both Piner backends report impossible closes with zero visible signals and undefined lower request. There is no confirmed author numeric rule."]],
               "results":[]})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
