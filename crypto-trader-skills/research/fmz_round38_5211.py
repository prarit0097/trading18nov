"""Reconcile FMZ #5211 source signals and the exit-reservation blocker."""

import math
import sys
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, read, sha256, write


SOURCE = "87d1baaa9640ed7295e3f287e91ecd6f8e2ef5d478016dea22f7411285f37f6d"
NATIVE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
ALTERNATE = "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea"
REVISION = "7853bb2bf262c4567ac238d3552d97f0e50cb801"
DAY = 86_400_000


def fixtures(work, node):
    raw = read(work / "5211-reservation.json")
    other = read(node / "5211-piner-fixtures.json")
    assert other["engine"] == ALTERNATE
    rows = {}
    for record in raw["cases"]:
        case = record["case"]
        native_rows = [[o["id"], o["barIndex"], o["qty"], o["price"]]
                       for o in record["orders"] if o["id"] != "long"]
        piner = other["results"][case]
        assert not piner["diagnostics"]
        remote_rows = [[o["exitBar"], o["exitPrice"], o["qty"]]
                       for o in piner["broker"]["closedTrades"]]
        rows[case] = {"native_exits": native_rows, "piner_exits": remote_rows}
    assert rows["tp1_only"] == {"native_exits": [["TP1", 2, 1, 105]], "piner_exits": [[2, 105, 5]]}
    assert rows["tp1_then_trail"] == {"native_exits": [["Trail stop", 3, 5, 120]], "piner_exits": [[2, 105, 5]]}
    assert rows["trail_then_tp1"]["native_exits"] == [["TP1", 2, 1, 105], ["Trail stop", 3, 4, 120]]
    assert rows["deferred_trail_then_update"] == rows["tp1_then_trail"]
    assert rows["same_timing_quantity_explicit"]["native_exits"][0] == ["TP1", 2, 1, 105]
    return rows


def market(candles, observed, marker, tick):
    chart = candles["chart"]
    normalized = observed["normalized"]
    assert len(chart) == 371 and candles["full_lower_bars"] == 106_848
    assert observed["market"] == candles["market"]
    assert observed["literal"]["errors"][0].startswith("E_UNKNOWN_FUNCTION")
    assert observed["head_full"] == observed["head_last"]
    assert not normalized["diagnostics"]
    plot = normalized["plots"]
    for lower, series in zip(candles["last"], zip(*(plot["scope " + name] for name in
                                  ("close", "source", "typical", "volume")), strict=True), strict=True):
        _, _, h, lo, close, volume = lower
        assert all(math.isclose(a, b, abs_tol=1e-10)
                   for a, b in zip((close, close, (h + lo + close) / 3, volume), series, strict=True))
    broker = normalized["broker"]
    assert [o["id"] for o in broker["orders"]] == ["long", "Trail stop"] * 2
    assert len(broker["trades"]) == 2 and broker["position"][-1]["size"] == 0
    assert all(o["barIndex"] and chart[o["barIndex"]][1] == o["price"]
               and plot["scope buy"][o["barIndex"] - 1] == 1
               for o in broker["orders"] if o["id"] == "long")
    assert observed["tp1_only_control"]["plots"]["scope buy"] == plot["scope buy"]
    control = observed["tp1_only_control"]["broker"]["orders"]
    assert control[0] == broker["orders"][0]
    first = control[1]
    assert (first["id"], first["barIndex"], first["qty"], first["price"]) == ("TP1", *marker)
    assert math.isclose(first["qty"], control[0]["qty"] * .20, abs_tol=.001)
    raw_limit = Decimal(str(control[0]["price"])) * Decimal("1.01")
    price_limit = (raw_limit / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    assert first["price"] == float(price_limit)
    start = chart[control[0]["barIndex"]][0] + DAY
    first_lower = next(bar for bar in candles["witness"]
                       if start <= bar[0] < start + DAY and bar[2] >= float(price_limit) and bar[-1] > 0)
    assert start == first["time"]
    return {"market": candles["market"], "archived_days":len(chart),
            "verified_5m_candles":candles["full_lower_bars"],
            "observation_time_utc":[iso_day(chart[0][0]), iso_day(chart[-1][0] + DAY)],
            "source_entry_signals":[chart[i][0] for i,buy in enumerate(plot["scope buy"]) if buy],
            "native_diagnostic_fills":broker["orders"],
            "native_diagnostic_reservation_omits_tp1":True,
            "first_tp1_on_control":first,
            "first_actual_5m_bar_touching_grid_target":first_lower,
            "target_activation_start":start,
            "literal_compiler_diagnostics":observed["literal"]["errors"]}


def main(work, node, output):
    assert sha256(work / "source-5211.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == NATIVE
    assert sha256(node / "package/dist/index.js") == ALTERNATE
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(v[0] == "PermissionError" for v in isolation.values())
    node_isolation = read(node / "isolation-probe.json")
    assert node_isolation == {"privateDenied":True, "networkDenied":True}
    feed = work / "5211-inputs.json"
    probe = work / "5211-probe.json"
    inputs = read(feed)
    markets = [market(data, native, marker, Decimal(tick)) for data,native,marker,tick in
               zip(inputs["cases"], read(probe), ((186,7.543,26773.9),(287,125.501,1609.24)), (".1",".01"), strict=True)]
    assert len(inputs["archive_receipts"]) == 52 and len(inputs["fx_receipts"]) == 3
    write(output, {"schema":"FMZ #5211 named partial exit and full trailing reservation evidence",
                   "source_url":"https://www.fmz.com/strategy/436221","source_revision":REVISION,"source_sha256":SOURCE,
                   "native_engine_sha256":NATIVE,"alternate_engine_sha256":ALTERNATE,
                   "input_sha256":sha256(feed),"native_probe_sha256":sha256(probe),
                   "native_reservation_fixture_sha256":sha256(work / "5211-reservation.json"),
                   "piner_reservation_fixture_sha256":sha256(node / "5211-piner-fixtures.json"),
                   "market_receipts":inputs["archive_receipts"],"fx_receipts":inputs["fx_receipts"],
                   "isolation":{"python":isolation,"node":node_isolation},
                   "markets":markets,"reservation_fixtures":fixtures(work,node),
                   "coverage":[[5211,"Pending · 20% TP1 and full-trail reservation",
                     "Replayed 371 archived daily bars with 106,848 validated 5m children per market. Pine Compat erases the named 20% limit when a later full trail is placed. Both Piner backends fill the entire isolated 20% exit. Exact reservation and trailing chronology remain unresolved."]],
                   "results":[]})


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
