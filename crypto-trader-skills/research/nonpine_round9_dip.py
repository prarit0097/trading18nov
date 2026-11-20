"""OctoBot Dip Analyser single-pair study using Binance spot data."""

import argparse
import csv
import hashlib
import json
import math
from collections import deque
from datetime import date
from io import TextIOWrapper
from itertools import pairwise
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics
from research.nonpine_round6_index import BUFFER, FEE, LOTS
from research.nonpine_round7_ladders import floor_lot

ID = 6007
BAR = 14_400
MIN_NOTIONAL = 5.0
START = 1000.0
MONTHS = (
    "2026-08",
    "2026-09",
    "2026-10",
    "2026-11-01",
    "2026-11-02",
    "2026-11-03",
    "2026-11-04",
)
WINDOWS = (("2026-09-23", "2026-10-21"), ("2026-10-21", "2026-11-05"))
SEGMENTS = (10, 8, 6, 5, 4, 3, 2, 1)


def utc_day(text):
    return (date.fromisoformat(text) - date(1970, 1, 1)).days * 86_400


def read_minute(folder, symbol):
    bars, hashes = [], {}
    for value in MONTHS:
        file = folder / f"klines-spot-{symbol}-1m-{value}.zip"
        freq = "daily" if len(value) == 10 else "monthly"
        url = f"https://data.binance.vision/data/spot/{freq}/klines/{symbol}/1m/{symbol}-1m-{value}.zip"
        with file.open("rb") as stream:
            hashes[url] = hashlib.file_digest(stream, "sha256").hexdigest()
        with ZipFile(file) as archive:
            [entry] = archive.namelist()
            with archive.open(entry) as raw:
                for row in csv.reader(TextIOWrapper(raw, encoding="ascii")):
                    at = int(row[0])
                    divisor = 1_000_000 if at >= 10**15 else 1000
                    assert int(row[6]) + 1 == at + 60 * divisor
                    at //= divisor
                    h, low, close, vol = map(float, row[2:6])
                    assert low <= close <= h and vol >= 0
                    assert not bars or at == bars[-1][0] + 60
                    bars.append((at, h, low, close, vol))
    assert bars[0][0] == utc_day("2026-08-01")
    assert bars[-1][0] + 60 == utc_day("2026-11-05")
    return bars, hashes


def klinger_difference(rows):
    previous_range = rows[0][0] - rows[0][1]
    previous_sum = rows[0][0] + rows[0][1] + rows[0][2]
    trend, mass = -1, 0.0
    fast = slow = signal = None
    out = []
    for high, low, close, vol in rows[1:]:
        total, amplitude = high + low + close, high - low
        direction = int(total > previous_sum) if total != previous_sum else trend
        if direction != trend:
            trend, mass = direction, previous_range
        mass += amplitude
        force = vol * abs(amplitude / mass * 2 - 1) * 100 * (1 if trend else -1)
        if fast is None:
            fast = slow = force
            signal = 0.0
        else:
            fast += (force - fast) * (2 / 36)
            slow += (force - slow) * (2 / 56)
        spread = fast - slow
        signal += (spread - signal) * (2 / 14)
        out.append(spread - signal)
        previous_range, previous_sum = amplitude, total
    return out


def rsis(closes, length):
    delta = [b - a for a, b in pairwise(closes)]
    gain = sum(max(0, d) for d in delta[:length]) / length
    loss = sum(max(0, -d) for d in delta[:length]) / length
    values = [100 * (gain / (gain + loss))] if gain + loss else []
    for d in delta[length:]:
        gain += (max(0, d) - gain) / length
        loss += (max(0, -d) - loss) / length
        if gain + loss:
            values.append(100 * (gain / (gain + loss)))
    return values


def new_low(values, factor, delay):
    return (
        len(values) > 1
        and min(values) in values[-delay - 1 :]
        and values[-1] / factor > min(values)
    )


def dip_note(slow, fast, current, weights):
    for block in sorted(weights, key=lambda r: r["slow_threshold"]):
        if slow < block["slow_threshold"]:
            for step in sorted(
                block["fast_thresholds"], key=lambda r: r["fast_threshold"]
            ):
                if fast < step["fast_threshold"] and current < step["fast_threshold"]:
                    return step["weights"]["price"], step["weights"]["volume"]
            break
    return None


def technical_note(rows, rsi):
    if len(rows) < 56:
        return None
    diff = klinger_difference(rows)
    last = len(diff) - 1
    if diff[-1] > 0:
        begin = next((i + 1 for i in range(last - 1, -1, -1) if diff[i] <= 0), 0)
    else:
        begin = next((i + 1 for i in range(last - 1, -1, -1) if diff[i] > 0), 0)
    if not new_low(diff[max(begin, len(diff) - 7) :], 0.9, 1):
        return None
    r = rsis([x[2] for x in rows], rsi["period"])
    if not new_low(r[-5:], 0.95, 2):
        return None
    slow, fast = r[-rsi["slow_eval_count"] :], r[-rsi["fast_eval_count"] :]
    return dip_note(
        sum(slow) / len(slow), sum(fast) / len(fast), r[-1], rsi["RSI_to_weight"]
    )


def realtime_note(values, price, vol, cfg):
    if len(values) < SEGMENTS[0]:
        return None
    limit = cfg["price_difference_threshold_percent"] / 100
    volume_factor = 1 + cfg["volume_difference_threshold_percent"] / 100
    p_triggers = v_triggers = 0
    for size in SEGMENTS:
        s = values[-size:]
        anchor = sum(x[0] for x in s) / size
        p_triggers += int(price > anchor * (1 + limit)) - int(
            price < anchor * (1 - limit)
        )
        v_triggers += int(vol > volume_factor * sum(x[1] for x in s) / size)
    if not p_triggers:
        return None
    intensity = abs(p_triggers / 8) * min(1, v_triggers / 8 + 0.2)
    return math.copysign(math.cos(1 - intensity), p_triggers)


def decisions(bars, rsi, instant):
    historical, recent = [], deque(maxlen=10)
    local_h = local_l = local_v = None
    previous_alert = 0.0
    orders, counts = {}, {"4h": 0, "sampled_1m": 0}
    for at, high, low, price, volume in bars:
        start = at - at % BAR
        if at == start:
            local_h, local_l, local_v = high, low, volume
        else:
            local_h, local_l = max(local_h, high), min(local_l, low)
            local_v += volume
        recent.append((price, volume))
        note = realtime_note(list(recent), price, volume, instant)
        active = note is not None and abs(note - previous_alert) >= 0.15
        if active:
            previous_alert = note
        partial = (local_h, local_l, price, local_v)
        if at + 60 == start + BAR:
            historical.append(partial)
            candidate = technical_note(historical, rsi)
            kind = "4h"
        elif active:
            candidate = technical_note([*historical, partial], rsi)
            kind = "sampled_1m"
        else:
            continue
        if candidate is not None:
            orders[at] = start, *candidate, kind
            counts[kind] += 1
    return orders, counts


def ask_ladder(price, quantity, multiplier, lot, preferred):
    for count in range(preferred, 0, -1):
        step = (price * multiplier - price) / count
        part = floor_lot(quantity / count, lot)
        if part >= lot and part * (price + step) >= MIN_NOTIONAL:
            return [
                (
                    round(floor_lot(price + step * (i + 1), 0.01), 2),
                    part if i < count - 1 else quantity - part * (count - 1),
                )
                for i in range(count)
            ]
    return []


def sample_receipt(at, entry, exit_price, sold):
    gross = sold * (exit_price - entry)
    fees = sold * (exit_price * FEE + entry * FEE / (1 - FEE))
    execution = sold * BUFFER * (exit_price + entry / (1 - FEE))
    return at, gross, fees, execution


def replay(bars, signals, lo, hi, lot, settings):
    cash, bid, last = START, None, None
    asks, closed, ledger = [], [], []
    opened, dust = 0, 0.0
    for at, high, low, price, traded in bars:
        if at < lo:
            continue
        if at >= hi:
            break
        remaining = traded
        live_asks = []
        for ident, leg, ask, quantity, entry in sorted(
            asks, key=lambda x: (x[2], x[0], x[1])
        ):
            if high > ask and remaining >= quantity:
                remaining -= quantity
                cash += quantity * ask * (1 - FEE - BUFFER)
                closed.append(sample_receipt(at + 60, entry, ask, quantity))
                ledger.append(
                    {
                        "position": ident,
                        "leg": leg,
                        "close": at + 60,
                        "price": ask,
                        "quantity": quantity,
                    }
                )
            else:
                live_asks.append((ident, leg, ask, quantity, entry))
        asks = live_asks
        if bid is not None:
            entry, quantity, weight = bid
            if low < entry and remaining >= quantity:
                cash -= entry * quantity * (1 + BUFFER)
                base_net = quantity * (1 - FEE)
                usable = floor_lot(base_net, lot)
                levels = ask_ladder(
                    entry, usable, settings["price"][weight - 1], lot, settings["count"]
                )
                opened += 1
                dust += base_net - sum(q for _, q in levels)
                ledger.append(
                    {
                        "position": opened,
                        "entry": at + 60,
                        "price": entry,
                        "quantity": quantity,
                        "targets": levels,
                    }
                )
                asks.extend(
                    (opened, i, p, q, entry) for i, (p, q) in enumerate(levels, 1)
                )
                bid = None
        if at in signals:
            candle, price_w, volume_w, _kind = signals[at]
            if candle != last or bid is not None:
                entry = round(floor_lot(price * 0.995, 0.01), 2)
                quantity = floor_lot(
                    cash / price * 0.5 * settings["volume"][volume_w - 1], lot
                )
                bid = (
                    (entry, quantity, price_w)
                    if quantity * entry >= MIN_NOTIONAL
                    else None
                )
                last = candle
                assert not bid or bid[0] * bid[1] * (1 + BUFFER) <= cash + 1e-9
        assert cash >= -1e-8 and dust >= -1e-10
    return (
        closed,
        len({a[0] for a in asks}),
        {
            "fills": ledger,
            "free_quote": cash,
            "waiting_buy": bid,
            "base_dust": dust,
            "open_target_orders": len(asks),
        },
    )


def run(binance, archive_path, baseline, output):
    [entry] = [r for r in read(baseline)["disposition"] if r["id"] == ID]
    assert entry["status"] == "Framework inputs needed"
    rev = entry["source"].split("/blob/")[1].split("/")[0]
    prefix = f"OctoBot-Tentacles-{rev}/"
    profile = "profiles/dip_analyser/"
    files = (
        profile + "profile.json",
        profile + "specific_config/DipAnalyserTradingMode.json",
        profile + "specific_config/RSIWeightMomentumEvaluator.json",
        profile + "specific_config/InstantFluctuationsEvaluator.json",
        profile + "specific_config/DipAnalyserStrategyEvaluator.json",
        "Trading/Mode/dip_analyser_trading_mode/dip_analyser_trading.py",
        "Evaluator/Strategies/dip_analyser_strategy_evaluator/dip_analyser_strategy.py",
        "Evaluator/RealTime/instant_fluctuations_evaluator/instant_fluctuations.py",
        "Evaluator/TA/momentum_evaluator/momentum.py",
        "Evaluator/Util/trend_analysis/trend_analysis.py",
    )
    with ZipFile(archive_path) as archive:
        material = [archive.read(prefix + f) for f in files]
    config, settings, rsi, instant, evaluator = map(json.loads, material[:5])
    assert evaluator["required_time_frames"] == ["4h"] and instant["time_frame"] == "1m"
    assert config["config"]["trader-simulator"]["starting-portfolio"]["USDT"] == START
    alpha = ("light", "medium", "heavy")
    parms = {
        "price": [settings[f"{w}_weight_price_multiplier"] for w in alpha],
        "volume": [settings[f"{w}_weight_volume_multiplier"] for w in alpha],
        "count": settings["sell_orders_count"],
    }

    results, evidence, receipts = [], {}, {}
    for symbol, lot in LOTS.items():
        source, data = read_minute(binance, symbol)
        signals, kinds = decisions(source, rsi, instant)
        evidence[symbol] = {
            "data": data,
            "minute_candles": len(source),
            "decision_counts": kinds,
        }
        for first, last in WINDOWS:
            lo, hi = utc_day(first), utc_day(last)
            pnl, unsettled, observed = replay(source, signals, lo, hi, lot, parms)
            key = f"{first} through {last} UTC"
            receipts[f"{symbol}/{first}"] = observed
            results.append(
                {
                    "id": ID,
                    "period": key,
                    "group": "OctoBot Dip Analyser · single-pair historical variant",
                    "market": symbol,
                    "currency": "USDT",
                    "interval": "4h plus 1m sampled interruption",
                    "archive_interval": "4h and 1m fluctuation trigger",
                    "exit": "Weighted source profit ladder",
                    "order_family": "Passive limit entry and split exit",
                    **metrics(pnl, unsettled),
                }
            )
            print(symbol, first, len(pnl), unsettled, flush=True)
    label = "Tested · OctoBot Dip Analyser single-pair replay"
    if not any(x["trades"] for x in results):
        label += ", no closes"
    write(
        output,
        {
            "coverage": [
                [
                    ID,
                    label,
                    (
                        "Pinned 4h Klinger and RSI thresholds with the published 1m fluctuation trigger. "
                        "Each BTC/ETH spot pair starts with 1,000 USDT under the single-asset sizing branch. "
                        "Strict later-candle trade-through and volume qualify resting orders."
                    ),
                ]
            ],
            "results": results,
            "evidence": evidence,
            "receipts": receipts,
            "source_sha256": {
                f: hashlib.sha256(d).hexdigest()
                for f, d in zip(files, material, strict=True)
            },
            "indicator_source": "https://github.com/TulipCharts/tulipindicators/tree/be18abb13e075ba866898dcc7cb52399603302a6/indicators",
            "execution_source": "https://github.com/Drakkar-Software/OctoBot-Trading/blob/1ad2f4d6d2961cd28d5405472c4d2cc81ddbcfa2/octobot_trading/personal_data/orders/order_util.py",
            "assumptions": "The published profile uses a shared three-pair portfolio seeded with BTC. "
            "This labeled study isolates the profile signal and the source single-asset sizing branch with no pre-existing base exposure. "
            "The realtime trigger observes closed one-minute data and the incomplete four-hour bar then available. "
            "The model does not assert queue priority. Realized drawdown uses a 10,000 USDT reference. "
            "Partial ladder exits allocate entry costs by filled base quantity.",
            "fees": {
                "entry_base_rate": FEE,
                "exit_quote_rate": FEE,
                "execution_buffer": BUFFER,
            },
            "settings": parms,
        },
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for n in ("binance", "archive", "baseline", "output"):
        cli.add_argument(n, type=Path)
    args = cli.parse_args()
    run(args.binance, args.archive, args.baseline, args.output)
