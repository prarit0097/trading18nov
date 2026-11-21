"""Replay #5211 with explicit partial-exit reservations and recorded price ranges."""

import math
import sys
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round26_977 import prices
from research.fmz_round37_pine_andy import rsi
from research.fmz_round38_5211 import DAY, SOURCE
from research.fmz_round45_3366 import grid

FEE = Decimal(".0007")
LOT = Decimal(".001")
CAPITAL = Decimal(1_000_000)
PRIOR = "4429ee00caaefd9485257ed28ee5a38c7e8e8d974b67c22e507bd2951dad737c"
FIVE = 300_000
MONTHS = ("2022-12", *(f"2023-{i:02d}" for i in range(1, 13)))


def seeded(values, n, warm):
    prior = None
    result = []
    for i, value in enumerate(values):
        if warm and i < n - 1:
            result.append(None)
            continue
        if prior is None:
            prior = math.fsum(values[:n]) / n if warm else value
        else:
            prior += 2 / (n + 1) * (value - prior)
        result.append(prior)
    return result


def cross_up(a, b, previous_a, previous_b):
    return (
        None not in (a, b, previous_a, previous_b)
        and a > b
        and previous_a <= previous_b
    )


def independent(chart, lower, warm_ribbon=True):
    closes = [c[4] for c in lower]
    typ = [(x[2] + x[3] + x[4]) / 3 for x in lower]
    vol = [x[5] for x in lower]
    strength = rsi(closes, 34)
    ribbon = seeded(closes, 39, warm_ribbon)
    macd = [
        a - b
        for a, b in zip(
            seeded(closes, 7, False), seeded(closes, 23, False), strict=True
        )
    ]
    signal = seeded(macd, 10, False)
    mf = []
    pos = []
    neg = []
    buys = []
    stops = []
    refs = []
    ups = []
    atr = entry_ref = None
    for i, (bar, base) in enumerate(zip(chart, lower, strict=True)):
        previous = typ[i - 1] if i else None
        pos.append(vol[i] * typ[i] if previous is None or typ[i] > previous else 0)
        neg.append(vol[i] * typ[i] if previous is None or typ[i] < previous else 0)
        up_flow, down_flow = (
            (math.fsum(x[i - 14 : i + 1]) for x in (pos, neg))
            if i >= 14
            else (None, None)
        )
        mf.append(
            None
            if down_flow is None or (not down_flow and not up_flow)
            else 100
            if not down_flow
            else 100 - 100 / (1 + up_flow / down_flow)
        )
        up = (
            i >= 38
            and ribbon[i] is not None
            and ribbon[i] > math.fsum(closes[i - 38 : i + 1]) / 39
        )
        ups.append(up)
        trigger = i and (
            cross_up(macd[i], signal[i], macd[i - 1], signal[i - 1])
            or (up and cross_up(mf[i], 12, mf[i - 1], 12))
        )
        raw = bool(
            trigger
            and strength[i] is not None
            and strength[i] < 50
            and bar[4] > math.fsum(closes[i - 2 : i + 1]) / 3
        )
        if raw:
            entry_ref = bar[4]
        if i:
            tr = max(
                base[2] - base[3],
                abs(base[2] - closes[i - 1]),
                abs(base[3] - closes[i - 1]),
            )
            atr = tr if atr is None else atr + (tr - atr) / 40
        buys.append(raw and up)
        stops.append(
            entry_ref is not None and atr is not None and bar[4] < entry_ref - 2 * atr
        )
        refs.append(entry_ref)
    return {
        "macd": macd,
        "signal": signal,
        "mf": mf,
        "rsi": strength,
        "up": ups,
        "buy": buys,
        "stop": stops,
        "trail reference": refs,
    }


def check_plot(witness, observed, tick):
    for key, values in witness.items():
        native = observed[
            "scope " + ("trail ticks" if key == "trail reference" else key)
        ]
        for i, (a, b) in enumerate(zip(values, native, strict=True)):
            if key == "trail reference" and a is not None:
                a = a * 0.013 / float(tick)
            assert (
                b is None
                if a is None
                else b is not None and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9)
            ), (key, i, a, b)


@dataclass(frozen=True)
class Exits:
    reserved_tp: Decimal
    reserved_trail: Decimal
    best: Decimal | None


def intrabar(values, state, limit, activation, offset, tick):
    fills = []
    for i, p in enumerate(values):
        if state.reserved_tp and limit is not None and p >= limit:
            fills.append(("TP1", state.reserved_tp, p if i == 0 else limit))
            state = replace(state, reserved_tp=Decimal(0))
        if not state.reserved_trail:
            continue
        if state.best is not None:
            stop = grid(state.best - offset, tick, ROUND_FLOOR)
            if p <= stop:
                fills.append(("Trail", state.reserved_trail, p if i == 0 else stop))
                state = replace(state, reserved_trail=Decimal(0), best=None)
                continue
        if p >= activation or state.best is not None:
            state = replace(state, best=p if state.best is None else max(p, state.best))
    return fills, state


def financial_fill(order, entry, amount, stamp, opening_rate, exit_rate):
    reason, price = order
    entry_usd = entry[1] * opening_rate
    exit_usd = price * exit_rate
    fee = (entry_usd + exit_usd) * amount * FEE
    return {
        "dir": 1,
        "qty": float(amount),
        "entryTime": entry[0],
        "exitTime": stamp,
        "entryPrice": float(entry_usd),
        "exitPrice": float(exit_usd),
        "commission": float(fee),
        "profit": float((exit_usd - entry_usd) * amount - fee),
        "exit_reason": reason,
        "quote_entry_price": float(entry[1]),
        "quote_exit_price": float(price),
    }


def settle(market, chart, lower, rates, signals, restart, renew):
    tick = Decimal(".1" if market == "BTCUSDT" else ".01")
    cash = CAPITAL
    position = Decimal(0)
    legs = []
    entries = []
    entry = None
    has_tp = False
    best = None
    for i, bar in enumerate(chart[1:], 1):
        stamp, open_price = bar[:2]
        p = Decimal(str(open_price))
        fx = rates[stamp]
        had_position = bool(position)
        if had_position and signals["stop"][i - 1]:
            legs.append(
                financial_fill(
                    ("Market condition", p), entry, position, stamp, rates[entry[0]], fx
                )
            )
            cash += p * position * fx * (1 - FEE)
            position = Decimal(0)
            best = None
        if not had_position and signals["buy"][i - 1]:
            position = cash / (p * fx * (1 + FEE)) // LOT * LOT
            cash -= p * position * fx * (1 + FEE)
            assert position > 0 and cash >= 0
            entry = (stamp, p)
            entries.append({"stamp": stamp, "price": float(p), "qty": float(position)})
            has_tp = False
            best = None
        if not position:
            continue
        target = (
            grid(entry[1] * Decimal("1.01"), tick, ROUND_CEILING)
            if had_position
            else None
        )
        reserved_tp = (
            position * Decimal(".20") // LOT * LOT
            if target is not None and (renew or not has_tp)
            else Decimal(0)
        )
        reserve = Exits(reserved_tp, position - reserved_tp, None if restart else best)
        offset = Decimal(str(signals["trail reference"][i - 1])) * Decimal(".013")
        activate = grid(entry[1] + offset, tick, ROUND_CEILING)
        for sub in lower[i * 288 : (i + 1) * 288]:
            t, o, h, l, c, v = sub
            if not v:
                continue
            o, h, l, c = (Decimal(str(q)) for q in (o, h, l, c))
            first = intrabar((o, h, l, c), reserve, target, activate, offset, tick)
            second = intrabar((o, l, h, c), reserve, target, activate, offset, tick)
            assert first == second, ("Finer tape needed", market, t, first, second)
            completed, reserve = first
            for reason, qty, fill in completed:
                assert 0 < qty <= position
                position -= qty
                cash += fill * qty * fx * (1 - FEE)
                legs.append(
                    financial_fill((reason, fill), entry, qty, t, rates[entry[0]], fx)
                )
                if reason == "TP1":
                    has_tp = True
            if not position:
                assert reserve.reserved_tp == reserve.reserved_trail == 0
                break
        best = reserve.best
        assert reserve.reserved_tp + reserve.reserved_trail == position
    terminal = None
    if position:
        mark = Decimal(str(chart[-1][4])) * rates[chart[-1][0]]
        terminal = {
            "qty": float(position),
            "entry": float(entry[1]),
            "mark_usd": float(mark),
            "cash": float(cash),
            "equity": float(cash + mark * position),
        }
    return {
        "entries": entries,
        "settled": legs,
        "terminal": terminal,
        "ending_cash": float(cash),
    }


def main(document, stage, probe, prior_path, native_lower, output):
    assert sha256(document) == SOURCE and sha256(prior_path) == PRIOR
    audit = read(prior_path)
    assert (
        sha256(stage) == audit["input_sha256"]
        and sha256(probe) == audit["native_probe_sha256"]
    )
    inputs = read(stage)
    rates = {
        q["effectiveTime"]: Decimal(str(q["rate"]))
        for q in inputs["fx"]["pairs"][0]["rates"]
    }
    cases = []
    receipts = []
    for case, observed in zip(inputs["cases"], read(probe), strict=True):
        market = case["market"]
        assert market == observed["market"]
        chart = case["chart"]
        lower = prices(
            verified_archives(native_lower, market, "5m", MONTHS, receipts),
            chart[0][0],
            chart[-1][0] + DAY,
            FIVE,
        )
        assert [list(r) for r in lower[287::288]] == case["last"]
        assert [list(r[:5]) for r in aggregate(lower, 288)] == [r[:5] for r in chart]
        tick = Decimal(".1" if market == "BTCUSDT" else ".01")
        witness = independent(chart, case["last"])
        check_plot(witness, observed["normalized"]["plots"], tick)
        alternate = independent(chart, case["last"], warm_ribbon=False)
        assert all(
            witness[k] == alternate[k] for k in ("buy", "stop", "trail reference")
        )
        variants = {}
        for restart, renew in (
            (False, False),
            (False, True),
            (True, False),
            (True, True),
        ):
            model = settle(
                market, chart, lower, rates, witness, restart=restart, renew=renew
            )
            variants[f"restart={restart}, renew={renew}"] = {
                "entries": model["entries"],
                "exit_events": [
                    {
                        key: leg[key]
                        for key in (
                            "qty",
                            "entryTime",
                            "exitTime",
                            "quote_exit_price",
                            "exit_reason",
                        )
                    }
                    for leg in model["settled"]
                ],
                "still_open": model["terminal"] is not None,
            }
        cases.append(
            {
                "market": market,
                "checked_daily_bars": len(chart),
                "checked_5m_bars": len(lower),
                "policies": variants,
            }
        )
    assert any(
        any(v != next(iter(c["policies"].values())) for v in c["policies"].values())
        for c in cases
    )
    write(
        output,
        {
            "schema": "FMZ #5211 historical TP renewal and trailing amendment sensitivity",
            "source_url": audit["source_url"],
            "source_sha256": SOURCE,
            "prior_sha256": PRIOR,
            "lower_timeframe_receipts": receipts,
            "cases": cases,
            "results": [],
            "notes": "Independent formulas matched all daily decisions and native indicator traces. Both five-minute paths agreed for each book and policy. Exit-order amendments at subsequent chart closes still affect the settled quantities or prices. This diagnostic uses four declared amendment policies and does not infer the original FMZ host's choice.",
            "reference": "https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/#partial-and-multi-level-exits",
            "coverage": [
                [
                    5211,
                    "Pending · named exit amendment changes settlement",
                    "All 371 daily decisions per market and offline five-minute paths agree with independent checks. Differing trailing and partial take-profit amendment policies change ETH settlement. Original FMZ host evidence for these amendments remains missing.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
