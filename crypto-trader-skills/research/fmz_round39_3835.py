"""Independently verify FMZ #3835's BTC-only no-order historical scope."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round32_trailing_offset import sma

SOURCE = "bb8bcf3005a529e1150b0bfa4254e3697976d76597e42379153df1ed9e017062"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 50_000


def factors(chart, seed_from_first=False):
    close = [bar[4] for bar in chart]
    fast, slow = sma(close, 20), sma(close, 50)
    filtered, ha, stochastic = [], [], []
    alpha = 2 / 201
    for i, (_, op, high, low, price, _) in enumerate(chart):
        if seed_from_first and i == 0:
            ema = price
        elif not seed_from_first and i < 199:
            ema = None
        elif not seed_from_first and i == 199:
            ema = math.fsum(close[:200]) / 200
        else:
            ema = alpha * price + (1 - alpha) * filtered[-1]
        filtered.append(ema)
        ha.append(((op + price) / 2 if i == 0 else (ha[-1][0] + ha[-1][1]) / 2,
                   (op + high + low + price) / 4))
        if i < 9:
            stochastic.append(None)
        else:
            recent = chart[i - 9:i + 1]
            hh, ll = max(r[2] for r in recent), min(r[3] for r in recent)
            stochastic.append(100 * (price - ll) / (hh - ll))
    k = sma(stochastic, 3)
    d = sma(k, 3)
    score = []
    for i in range(len(chart)):
        ha_up = (i >= 2 and ha[i][0] < ha[i][1] and ha[i - 1][0] < ha[i - 1][1]
                 and ha[i - 2][0] >= ha[i - 2][1])
        trend_up = (filtered[i] is not None and slow[i] is not None
                    and fast[i] > slow[i] > filtered[i])
        stochastic_up = (i > 0 and d[i - 1] is not None and k[i] > d[i]
                         and k[i] > k[i - 1] and d[i] > d[i - 1])
        score.append(int(ha_up) + int(trend_up) + int(stochastic_up))
    return {"ha open": [r[0] for r in ha], "ha close": [r[1] for r in ha],
            "fast": fast, "slow": slow, "filter": filtered, "K": k, "D": d, "bull": score}


def equal_series(expected, observed):
    return all((a is None and b is None) or
               (a is not None and b is not None and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9))
               for a,b in zip(expected, observed, strict=True))


def audit_market(market, chart, replay):
    assert len(chart) == 371
    failure, = replay["literal"]["errors"]
    assert failure.startswith("E_PARSE_EXPR:Error:")
    result = replay["relocated"]
    assert replay["constant_quantity"] == result and not result["diagnostics"]
    broker, plots = result["strategy"], result["plots"]
    for name, series in factors(chart).items():
        assert equal_series(series, plots["scope " + name]), name
    assert plots["scope capital"] == [CAPITAL] * len(chart)
    assert plots["scope bear"] == [0] * len(chart)
    qty = [math.floor(CAPITAL * .1 / row[4]) for row in chart]
    assert qty == plots["scope quantity"]
    expected_signal_count = sum(n > 1 for n in plots["scope bull"])
    first_seed_signal_count = sum(n > 1 for n in factors(chart, True)["bull"])
    no_stop = replay["no_stop_control"]["strategy"]
    if market == "BTCUSDT":
        assert expected_signal_count == 62 and first_seed_signal_count == 83
        assert max(qty) == 0 and min(row[3] for row in chart) > 5000
        assert not broker["orders"] and not broker["trades"] and not broker["diagnostics"]
        assert broker == no_stop
        assert len(broker["equity"]) == len(chart)
        assert all(row["cash"] == row["equity"] == CAPITAL and row["marketValue"] == row["netProfit"] == 0
                   for row in broker["equity"])
    else:
        assert expected_signal_count == 46 and first_seed_signal_count == 72
        assert min(qty) == 2 and max(qty) == 4
        assert [d["code"] for d in broker["diagnostics"]] == ["E_STRATEGY_PRICE"] * 46
        assert not broker["orders"] and len(no_stop["trades"]) == 38
    return {"market":market,"literal_compilation":failure,"close_minimum":min(row[4] for row in chart),
            "low_minimum":min(row[3] for row in chart),"unit_range":[min(qty),max(qty)],
            "bull_eligible_native_ema_seed":expected_signal_count,
            "bull_eligible_first_value_ema_control":first_seed_signal_count,
            "sourced_daily_bars":len(chart),"original_flat_stop_diagnostics":len(broker["diagnostics"]),
            "closes_without_stop_diagnostic":len(no_stop["trades"])}


def main(work, out):
    assert sha256(work / "source-3835.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    feed = work / "3835-feed.json"
    raw = work / "3835-native.json"
    data = read(feed)
    assert len(data["receipts"]) == 26
    native = read(raw)
    cases = [audit_market(m, chart, native[m]) for m, chart in data["markets"].items()]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error","network_error"}
    assert all(v[0] == "PermissionError" for v in isolation.values())
    rows = [{"id":3835,"market":"BTCUSDT","group":"FMZ Pine v4 · declaration relocation",
             "exit":"Archived close gates, no eligible entry size",
             "period":"Binance USD-M · 2022-12-08 to 2023-12-14 UTC exclusive",
             "interval":"1d","archive_interval":"1d","currency":"USDT",
             **ledger_metrics([], CAPITAL, 0)}]
    write(out, {"schema":"FMZ #3835 audited native BTC zero-size archived replay",
                "source_url":"https://www.fmz.com/strategy/435481",
                "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
                "source_sha256":SOURCE,"engine_sha256":ENGINE,"raw_sha256":sha256(raw),
                "input_sha256":sha256(feed),"market_receipts":data["receipts"],
                "cases":cases,"isolation":isolation,
                "coverage":[[3835,"Tested · BTC archived zero order size",
                             "Moving the source's sole capital literal into the declaration restores Pine compatibility. Every BTC chart low exceeds 5,000, independently proving zero explicit units after flooring across all 371 days. ETH diagnostic uses positive quantity and hits unresolved flat-stop semantics, so contributes no performance."]],
                "results":rows})


if __name__=="__main__":
    main(*map(Path, sys.argv[1:]))
