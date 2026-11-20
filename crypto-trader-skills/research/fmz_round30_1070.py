"""Independent order and execution audit for native FMZ 1070."""

import collections
import math
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, ledger_metrics, raw_ohlcv, read, sha256, verified_archives, write

FEE = .0003
CAPITAL = 10_000


def offset(ticks, tick):
    rounded = round(ticks)
    return (rounded if abs(ticks - rounded) <= 1e-9 else math.ceil(ticks)) * tick


def triggers(o, side, prev, entry, tick):
    direction = 1 if side == "L" else -1
    limit = o["limit" + side][prev]
    target = limit if limit is not None else entry + direction * offset(o["profit" + side][prev], tick)
    stop = entry - direction * offset(o["loss" + side][prev], tick)
    return target, stop


def bar_bracket(ohlc, side, target, stop):
    _, op, high, low, _, _ = ohlc
    is_long = side == "L"
    open_is_trigger = op >= target or op <= stop if is_long else op <= target or op >= stop
    if open_is_trigger:
        return op, "open", False
    hit_target = high >= target if is_long else low <= target
    hit_stop = low <= stop if is_long else high >= stop
    high_first = high - op < op - low
    target_first = high_first == is_long
    both = hit_target and hit_stop
    if hit_target and (not hit_stop or target_first):
        return target, "target", hit_stop
    if hit_stop:
        return stop, "stop", both
    return None, None, False


def reconcile(c, data, minute, tick):
    broker, o = c["broker"], c["observations"]
    chart = data["chart"]
    by_index = collections.defaultdict(list)
    for order in broker["orders"]:
        by_index[order["barIndex"]].append(order)
    zero = []
    anomalies = []
    off_grid = []
    dual_hit = []
    both_minutes = []
    minute_divergences = []
    market_fills = collections.Counter()
    bracket_types = collections.Counter()
    wrong = collections.Counter()
    verified = []
    assert all(not (l and s) for l, s in zip(o["signalL"], o["signalS"], strict=True))
    cash = CAPITAL
    previous_exit = None
    for t in sorted(broker["trades"], key=lambda t: t["entryBarIndex"]):
        e, x = t["entryBarIndex"], t["exitBarIndex"]
        entry, closed, qty = t["entryPrice"], t["exitPrice"], t["qty"]
        side = t["id"]
        assert qty * (1 if side == "L" else -1) > 0
        assert o["signal" + side][e-1] == 1 and chart[e][1] == entry
        assert minute[e*30][1] == entry
        assert t["entryTime"] == chart[e][0] and t["exitTime"] == chart[x][0]
        entries = [v for v in by_index[e] if v["id"] == side]
        assert len(entries) == 1 and entries[0]["price"] == entry
        transaction_qty = abs(qty)
        if previous_exit and previous_exit["exitBarIndex"] == e and not o["atrStop"][e-1]:
            transaction_qty += abs(previous_exit["qty"])
        if not math.isclose(transaction_qty, entries[0]["qty"], abs_tol=1e-10):
            wrong["transactions"] += 1
        entry_fee, exit_fee = FEE * abs(qty) * entry, FEE * abs(qty) * closed
        net = qty * (closed-entry) - entry_fee - exit_fee
        assert math.isclose(net, t["profit"], abs_tol=1e-8)
        budget = cash
        if previous_exit and previous_exit["exitBarIndex"] == e and not o["atrStop"][e-1]:
            budget += FEE * abs(previous_exit["qty"]) * entry
        round_lots = int(Decimal(f"{budget:.9e}") / (Decimal(str(entry)) * Decimal("1.0003")) * 1000) / 1000
        if not math.isclose(round_lots, abs(qty), abs_tol=1e-10):
            wrong["next_open_lots"] += 1
        for mid in range(e, x):
            target, stop = triggers(o, side, mid-1, entry, tick)
            assert not o["atrStop"][mid-1] or mid == e
            modeled, _, _ = bar_bracket(chart[mid], side, target, stop)
            assert modeled is None, (c["ref"]["market"], side, e, x, mid, modeled)
        cash += net
        previous_exit = t
        verified.append({**t, "qty": abs(qty), "dir": 1 if qty > 0 else -1, "commission": entry_fee + exit_fee})
        if not math.isclose(closed/tick, round(closed/tick), abs_tol=1e-7, rel_tol=0):
            off_grid.append({"exit_time": t["exitTime"], "price": closed,
                             "price_grid": tick, "raw_limit": o["limit"+side][x-1]})
        exit_events = [v for v in by_index[x] if v["id"] == "TP_"+side]
        if not exit_events:
            opposite = "S" if side == "L" else "L"
            reason = "atr_close" if o["atrStop"][x-1] else "reversal"
            assert chart[x][1] == minute[x*30][1] == closed
            if reason == "reversal":
                assert o["signal"+opposite][x-1] == 1 and any(a["id"] == opposite for a in by_index[x])
            market_fills[reason] += 1
        else:
            assert len(exit_events) == 1 and exit_events[0]["price"] == closed
            target, stop = triggers(o, side, x-1, entry, tick)
            modeled_price, event, both = bar_bracket(chart[x], side, target, stop)
            if modeled_price is None or not math.isclose(modeled_price, closed, abs_tol=1e-8):
                anomalies.append({"entry_bar": e, "exit_bar": x, "price": closed, "modeled": modeled_price,
                                  "target": target, "stop": stop, "open": chart[x][1], "side": side})
            if both:
                dual_hit.append(x)
            bracket_types[str(event)] += 1
            if e == x and entry == closed and o["profit"+side][x-1] == o["loss"+side][x-1] == 0 and o["limit"+side][x-1] is None:
                zero.append({"side": side, "signal_bar": e-1, "entry_bar": e, "price": entry,
                             "time": t["entryTime"], "qty": qty, "net": net})
            for k in range(x*30,x*30+30):
                reference, reference_reason, reference_both = bar_bracket(minute[k], side, target, stop)
                if reference is not None:
                    if both:
                        both_minutes.append({"exit_bar": x, "chart_time": chart[x][0],
                                             "chart_ohlc": chart[x][1:5], "target": target,
                                             "stop": stop, "minute_time": minute[k][0],
                                             "minute_ohlc": minute[k][1:5], "reason": reference_reason,
                                             "both_levels_in_minute": reference_both})
                    if not math.isclose(reference, closed, abs_tol=1e-8):
                        minute_divergences.append({"bar": x, "entry_time": t["entryTime"],
                                                   "minute_time": minute[k][0], "event": event,
                                                   "reference_event": reference_reason,
                                                   "minute_both_levels": reference_both,
                                                   "benchmark_price": closed,
                                                   "reference_price": reference})
                    break
            else:
                raise ValueError("Missing matching minute trigger")
    return {"market": c["ref"]["market"], "closed": len(broker["trades"]), "native_diagnostics": len(c["diagnostics"]),
            "next_open_quantity_mismatches": wrong["next_open_lots"], "zero_tick_same_open": zero,
            "transaction_quantity_mismatches": wrong["transactions"],
            "native_bracket_anomalies": anomalies, "market_fills": dict(market_fills),
            "bracket_fills": dict(bracket_types), "dual_level_count":len(dual_hit), "dual_level_receipts": both_minutes,
            "explicit_absolute_limits": {side: sum(v is not None for v in o["limit"+side]) for side in "LS"},
            "open_at_end":broker["position"][-1], "off_grid":off_grid,
            "minute_divergences":minute_divergences, "diagnostic_metrics":ledger_metrics(verified, CAPITAL, 1)}, verified


def fixture_evidence(raw, piner):
    expected_native = {
        "zero": [1, 1, 104, 104],
        "absolute_over_relative": [1, 2, 100, 105],
        "absolute_missing_uses_relative": [1, 1, 100, 102],
        "zero_joined_after_entry": [1, 2, 104, 110],
    }
    proof = {}
    for version in ("4", "5"):
        results = {}
        for name, expected in expected_native.items():
            native, = raw["fixtures"][version][name]["broker"]["trades"]
            version_case = piner["results"][version][name]
            assert not version_case["diagnostics"]
            other, = version_case["broker"]["closedTrades"]
            native_actual = [native[k] for k in ("entryBarIndex", "exitBarIndex", "entryPrice", "exitPrice")]
            alternate_actual = [other[k] for k in ("entryBar", "exitBar", "entryPrice", "exitPrice")]
            alternate_expected = expected_native["absolute_missing_uses_relative"] if name == "absolute_over_relative" else expected
            assert native_actual == expected and alternate_actual == alternate_expected
            results[name] = {"pine_compat": native_actual, "piner_js_and_interpreter": alternate_actual}
        proof[version] = results
    return proof


def main(work, public, piner_path, output):
    raw_path = work/"1070-native.json"
    raw = read(raw_path)
    assert raw["source_sha256"] == "3221a4acbc7f85c74470c2a08b96ed8360558517482ba3fd94b843b365573894"
    engine_sha = sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")
    assert engine_sha == "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
    assert all(c["year_bound_proof"] for c in raw["cases"])
    manifest = read(work/"1070-inputs.json")
    piner = read(piner_path)
    assert piner["engine"] == "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea"
    isolation = read(work/"round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    alternate_isolation = read(piner_path.with_name("isolation-probe.json"))
    assert alternate_isolation == {"privateDenied": True, "networkDenied": True}
    fixtures = fixture_evidence(raw, piner)
    partial, pooled, rows = [], [], []
    archives = []
    attrs = {"id": 1070, "group": "FMZ Pine v4 · grid-safe portable benchmark",
             "exit": "Protected absolute limits and relative bracket exits, reversals and ATR market closes",
             "period": "Binance USD-M · 2024-01-01 to 2024-02-01 UTC exclusive",
             "interval": "30m", "archive_interval": "unspecified", "currency": "USDT"}
    for c, ref, market, expected_closes, expected_zero, expected_off_grid in zip(
        raw["cases"], manifest["feeds"], ("BTCUSDT", "ETHUSDT"), (80, 99), (4, 12), (31, 45), strict=True
    ):
        assert ref == c["ref"] and ref["market"] == market
        path, = verified_archives(public, market, "1m", ("2024-01",), archives)
        first, end = map(date_ms, ("2024-01-01", "2024-02-01"))
        minute = list(raw_ohlcv(path, 60_000))
        assert [r[0] for r in minute] == list(range(first, end, 60_000))
        path = work/ref["file"]
        assert sha256(path) == ref["sha256"]
        data = read(path)
        reference = aggregate(minute, 30)
        assert [list(r[:5]) for r in reference] == [r[:5] for r in data["chart"]]
        tick = {"BTCUSDT":.1,"ETHUSDT":.01}[market]
        unrounded, _ = reconcile(c, data, minute, tick)
        normalized, ledger = reconcile({"ref": ref, **c["normalized"]}, data, minute, tick)
        for scope in (unrounded, normalized):
            assert scope["closed"] == expected_closes and len(scope["zero_tick_same_open"]) == expected_zero
            for key in ("native_diagnostics", "next_open_quantity_mismatches", "transaction_quantity_mismatches",
                        "native_bracket_anomalies", "minute_divergences"):
                assert not scope[key]
            assert all(not item["both_levels_in_minute"] for item in scope["dual_level_receipts"])
            assert scope["dual_level_count"] == (1 if market == "BTCUSDT" else 0)
        assert len(unrounded["off_grid"]) == expected_off_grid and not normalized["off_grid"]
        o = c["normalized"]["observations"]
        for side, direction in (("L", 1), ("S", -1)):
            for i, new in enumerate(o["limit" + side]):
                if new is None:
                    continue
                raw_limit = o["average"][i] * (1 + direction * o["targetRatio" + side][i])
                units = Decimal(str(raw_limit)) / Decimal(str(tick))
                nearest = round(units)
                expected_units = nearest if abs(units - nearest) <= Decimal("1e-9") else (
                    math.ceil(units) if direction > 0 else math.floor(units))
                assert math.isclose(new/tick, expected_units, abs_tol=1e-7, rel_tol=0)
                improvement = (new-raw_limit) * direction
                assert -1e-9 <= improvement <= tick + 1e-9
        before, after = (c["broker"]["trades"], c["normalized"]["broker"]["trades"])
        assert len(before) == len(after)
        changes = collections.Counter()
        for prior, later in zip(before, after, strict=True):
            assert all(prior[k] == later[k] for k in ("id", "entryTime", "entryPrice", "exitTime"))
            changes["exitPrices"] += not math.isclose(prior["exitPrice"], later["exitPrice"], abs_tol=1e-9, rel_tol=0)
            changes["quantities"] += prior["qty"] != later["qty"]
        partial.append({"literal": unrounded, "normalized": normalized, "changes": dict(changes),
                        "normalized_pine_sha256": c["normalized"]["source_sha256"]})
        rows.append({**attrs, "market": market, **normalized["diagnostic_metrics"]})
        pooled.extend(ledger)
    rows.append({**attrs, "market": "BTCUSDT + ETHUSDT", **ledger_metrics(pooled, 2 * CAPITAL, 2)})
    write(output, {
        "schema": "FMZ #1070 portable Pine v4 grid-safe execution benchmark",
        "source_url": "https://www.fmz.com/strategy/376261",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": raw["source_sha256"], "engine_sha256": engine_sha,
        "alternate_engine_sha256": piner["engine"], "raw_diagnostic_sha256": sha256(raw_path),
        "input_data": manifest, "minute_archives": archives, "fixtures": fixtures,
        "isolation": {"python": isolation, "node": alternate_isolation},
        "fixture_columns": ["entry_bar", "exit_bar", "entry_price", "exit_price"],
        "cases": partial,
        "limitations": [
            "The published FMZ source omits a market, date range, timeframe and host settings. January 2024 BTC and ETH Binance USD-M 30-minute bars are a comparison scope.",
            "The standard 30-minute charts, author-default same-timeframe request feeds and Heikin-Ashi recurrence are seeded at the first comparison candle. The archived stop-year default 3333 lies above its declared maximum 2222. Both stop years give identical order ledgers and observations in 2024.",
            "FMZ puts handling fees into strategy.position_avg_price and accepts some author strategy options through the interface. The source provides no FMZ UI execution settings. The comparisons use the source's Pine v4 declaration and a Pine Compat broker with a fee-exclusive position average.",
            "The original formula produces 31 BTC and 45 ETH non-grid price executions in the literal emulator. Performance rows use the direction-preserving tick-safe absolute-limit formula only.",
            "Actual 1-minute OHLC confirms chart-path ordering. Fills at chart open or at modeled trigger levels are simulated. The data contain candles, without queue position, spread or executable order-book quotes.",
            "Cost metrics use 0.03% per execution side, zero authored slippage and historical 0.001 base quantity step. The gross scenario uses the same closed lots and omits their commissions. Drawdown follows realized closed equity. Funding and an end-of-period liquidation are outside this benchmark.",
            "The Piner 0.13.0 JS and interpreter backends use the relative target where Pine v4/v5 require the supplied absolute target. Their comparison is limited to the controls.",
        ],
        "coverage": [[1070, "Tested · Binance BTC/ETH grid-safe Pine v4 comparison",
                      "179 reconciled historical closes. Every execution price is on the contract tick grid. One both-level BTC candle is resolved by Binance 1m data. One open lot per market remains. FMZ host settings and fee-inclusive average limit direct parity."]],
        "results": rows,
    })


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
