"""Run the 23 September–20 October 2026 Delta India testnet candle comparison.

From crypto-trader-skills: python -m research.delta_october_comparison
Use --cache to save or replay the public candles. No private endpoints are used.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
import time

from crypto_skills.delta_candidate_capture import BASE, IST, public_result
from crypto_skills.delta_plan import CRYPTO_DEMO_SYMBOLS, plan_batch
from crypto_skills.delta_signal import closed_breakout

START = datetime(2026, 9, 23, tzinfo=IST)
DAYS = 28
END = START + timedelta(days=DAYS)
FIRST, LAST = int(START.timestamp()), int(END.timestamp())
BAR = 300
HOLD = 2 * BAR
SYMBOLS = CRYPTO_DEMO_SYMBOLS
SERIES = (*SYMBOLS, *("MARK:" + s for s in SYMBOLS))
CASH = D("160.7083")
FEE = D("0.00059")
HALF_SPREAD = D("0.0002")


def fetch_page(job):
    symbol, start, end = job
    for retry in range(3):
        try:
            return symbol, public_result(
                "/history/candles", symbol=symbol, resolution="5m", start=start, end=end-1
            )
        except (OSError, RuntimeError):
            if retry == 2:
                raise
            time.sleep(2 ** retry)


def download():
    begin = FIRST - 86400
    page = 2 * 86400
    jobs = [(symbol, start, min(start + page, LAST))
            for start in range(begin, LAST, page) for symbol in SERIES]
    series = {symbol: [] for symbol in SERIES}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for symbol, bars in pool.map(fetch_page, jobs):
            series[symbol].extend(b for b in bars if begin <= b["time"] < LAST)
    return {s: sorted(bars, key=lambda b: b["time"]) for s, bars in series.items()}


def history(raw):
    all_bars = {}
    for symbol in SERIES:
        indexed = {}
        for row in raw[symbol]:
            stamp = row["time"]
            bar = {k: D(str(row[k])) for k in ("open", "high", "low", "close")}
            bar["volume"] = D(str(row.get("volume") or 0))
            assert stamp % BAR == 0 and stamp not in indexed
            assert 0 < bar["low"] <= min(bar["open"], bar["close"])
            assert max(bar["open"], bar["close"]) <= bar["high"] and bar["volume"] >= 0
            indexed[stamp] = dict(bar, time=stamp)
        all_bars[symbol] = indexed
    return all_bars


def prepare(bars, products):
    opportunities = {}
    coverage = Counter()
    for slot in range(FIRST, LAST, BAR):
        if slot // 3600 != (slot + HOLD) // 3600:
            coverage["excluded_hour_crossing"] += 1
            continue
        if (slot - FIRST) % 86400 + HOLD >= 86400:
            coverage["excluded_ist_day_crossing"] += 1
            continue
        markets = []
        try:
            for symbol in SYMBOLS:
                trades = bars[symbol]
                mark = bars["MARK:" + symbol]
                # Coverage mask is shared. Prices in the exit bars are not used in ranking.
                if any(t not in trades or t not in mark
                       for t in (slot, slot + BAR, slot + HOLD)):
                    raise KeyError("Replay candle missing")
                tail = [trades[t] for t in range(slot - 86400, slot, BAR)]
                signal = closed_breakout(tail[-21:], slot)
                mid = tail[-1]["close"]
                turnover = sum(b["close"] * b["volume"] for b in tail)
                product = products[symbol]
                ticker = dict(product_id=product["id"], timestamp=slot * 1_000_000,
                              turnover_usd=turnover,
                              quotes=dict(best_bid=mid*(1-HALF_SPREAD),
                                          best_ask=mid*(1+HALF_SPREAD)))
                markets.append((product, ticker, signal))
        except (KeyError, ValueError):
            coverage["excluded_incomplete_market_data"] += 1
            continue
        opportunities[slot] = markets
        coverage["usable_slots"] += 1
        coverage["four_ready_slots"] += sum(s["status"] == "ready" for _, _, s in markets) >= 4
    return opportunities, coverage


def settle(order, slot, bars, cost):
    symbol = order["symbol"]
    trades, marks = bars[symbol], bars["MARK:" + symbol]
    entry = trades[slot]["open"] * (1 + cost)
    if trades[slot]["volume"] == 0 or entry > D(order["limit"]):
        return None
    qty, stop, target = (D(order[key]) for key in ("quantity", "stop", "target"))
    mark_exit = False
    exit_reason = "timer"
    for stamp in (slot, slot + BAR):
        mark = marks[stamp]
        if mark["low"] <= stop:
            reference = min(stop, mark["open"])
            exit_reason = "stop"
            break
        if mark["high"] >= target:
            reference = target
            exit_reason = "target"
            break
    else:
        timer = trades[slot + HOLD]
        mark_exit = timer["volume"] == 0
        reference = marks[slot + HOLD]["open"] if mark_exit else timer["open"]
    exit_price = reference * (1 - cost)
    gross = (exit_price - entry) * qty
    fee = (entry + exit_price) * qty * FEE
    return gross, fee, gross - fee, mark_exit, exit_reason


def simulate(opportunities, bars, ready_only, added_cost):
    results = []
    curve = peak = drawdown = D(0)
    filled, fees, gross = [], D(0), D(0)
    count = Counter()
    for index in range(DAYS):
        start = FIRST + index * 86400
        day_net = D(0)
        next_slot = start
        daily = Counter()
        for slot in range(start, start + 86400, BAR):
            if slot < next_slot or slot not in opportunities:
                continue
            markets = opportunities[slot]
            if ready_only:
                markets = [m for m in markets if m[2]["status"] == "ready"]
            if len(markets) < 4:
                continue
            plan = plan_batch(markets, slot, max(D(0), CASH + day_net),
                              max(D(0), -day_net), contracts=3)
            if plan["status"] != "planned":
                daily["risk_or_margin_blocked"] += 1
                continue
            assert len(plan["entries"]) == 4
            assert D(plan["planned_loss"]) + max(D(0), -day_net) <= 30
            assert D(plan["margin_reserve"]) <= D(plan["margin_budget"])
            assert all(D(o["planned_loss"]) <= 10 and o["leverage"] <= 5 for o in plan["entries"])
            daily["attempted_baskets"] += 1
            basket = [settle(o, slot, bars, HALF_SPREAD + added_cost) for o in plan["entries"]]
            basket = [r for r in basket if r is not None]
            daily["zero_fills"] += 4 - len(basket)
            if not basket:
                continue
            daily["filled_baskets"] += 1
            next_slot = slot + HOLD
            basket_net = D(0)
            for g, f, n, fallback, reason in basket:
                filled.append(n)
                daily["positions"] += 1
                daily["wins"] += n > 0
                daily["mark_timer_fallbacks"] += fallback
                daily["exit_" + reason] += 1
                gross += g
                fees += f
                basket_net += n
            day_net += basket_net
            curve += basket_net
            peak = max(peak, curve)
            drawdown = max(drawdown, peak-curve)
        results.append(dict(date=(START + timedelta(days=index)).date().isoformat(),
                            net_usd=str(day_net), **daily))
        count.update(daily)
    total = sum(filled, D(0))
    assert total == sum(D(row["net_usd"]) for row in results)
    assert abs(total - (gross - fees)) < D("1e-22")
    return dict(**count, gross_usd=str(gross), fees_usd=str(fees), net_usd=str(total),
                mean_usd=str(total/len(filled)) if filled else None,
                win_rate=str(D(count["wins"])/len(filled)) if filled else None,
                profitable_days=sum(D(r["net_usd"]) > 0 for r in results),
                drawdown_usd=str(drawdown), days=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.cache and args.cache.exists():
        raw = json.loads(args.cache.read_bytes())
    else:
        raw = download()
        if args.cache:
            args.cache.write_text(json.dumps(raw), encoding="utf-8")
    bars = history(raw)
    products = json.loads(Path("runs/trade1/candidate-input-products.json").read_bytes())["products"]
    opportunities, coverage = prepare(bars, products)
    coverage_by_day = Counter(
        datetime.fromtimestamp(slot, IST).date().isoformat() for slot in opportunities
    )
    payload = dict(
        type="historical_candle_screen", source=BASE, resolution="5m",
        from_ist=START.isoformat(), to_ist_exclusive=END.isoformat(),
        candle_counts={symbol: len(rows) for symbol, rows in bars.items()},
        candle_sha256={symbol: sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                       for symbol, rows in raw.items()},
        coverage=dict(coverage),
        usable_slots_by_ist_day={
            (START + timedelta(days=i)).date().isoformat():
            coverage_by_day[(START + timedelta(days=i)).date().isoformat()]
            for i in range(DAYS)
        },
        starting_cash_each_day_usd=str(CASH), fee_each_side=str(FEE),
        half_spread_each_side=str(HALF_SPREAD), extra_slippage_each_side={"base": "0.0001", "stress": "0.0005"},
        arms={f"{rule}_{scenario}": simulate(opportunities, bars, rule == "four_ready", extra)
              for scenario, extra in (("base", D(".0001")), ("stress", D(".0005")))
              for rule in ("baseline", "four_ready")},
    )
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
