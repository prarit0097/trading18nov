"""Replay Hummingbot's four standalone directional controllers with one-minute fills."""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "deps")]
import numpy as np
import talib

import nonpine_freqtrade as market

CASES = {
    5963: "bollinger_v1",
    5964: "bollinger_v2",
    5967: "macd_bb_v1",
    5968: "supertrend_v1",
}
SOURCE = "3351adad0a09f6a57a202219d3e52fe794672421"
STOP, TARGET, LIFETIME = 0.03, 0.02, 45 * 60
COOLDOWN = 5 * 60
FEE, EXTRA, SIZE = market.FEE, market.EXECUTION, market.STAKE


def signals(id_, frame):
    c = frame.close.to_numpy()
    if id_ == 5968:
        high, low = frame.high.to_numpy(), frame.low.to_numpy()
        width = talib.ATR(high, low, c, timeperiod=20) * 4
        upper = (high + low) / 2 + width
        lower = (high + low) / 2 - width
        direction = np.ones(len(c), dtype="int8")
        support = np.full(len(c), np.nan)
        for j in range(1, len(c)):
            if c[j] > upper[j - 1]:
                direction[j] = 1
            elif c[j] < lower[j - 1]:
                direction[j] = -1
            else:
                direction[j] = direction[j - 1]
                if direction[j] == 1 and lower[j] < lower[j - 1]:
                    lower[j] = lower[j - 1]
                if direction[j] == -1 and upper[j] > upper[j - 1]:
                    upper[j] = upper[j - 1]
            support[j] = lower[j] if direction[j] == 1 else upper[j]
        return np.where(np.abs(c - support) / c < 0.01, direction, 0)
    up, _, down = talib.BBANDS(c, timeperiod=100, nbdevup=2.0, nbdevdn=2.0)
    long = c < down
    short = c > up
    if id_ == 5967:
        macd, _, hist = talib.MACD(c, fastperiod=21, slowperiod=42, signalperiod=9)
        long &= (hist > 0) & (macd < 0)
        short &= (hist < 0) & (macd > 0)
    return np.where(long, 1, np.where(short, -1, 0))


def bar_exit(side, basis, opened, now, bar):
    if now >= opened + LIFETIME:
        return bar.open, now
    stop_at = basis * (1 - STOP * side)
    take_at = basis * (1 + TARGET * side)
    if (side == 1 and bar.low <= stop_at) or (side == -1 and bar.high >= stop_at):
        price = min(stop_at, bar.open) if side == 1 else max(stop_at, bar.open)
        return price, now + 60
    if (side == 1 and bar.high > take_at) or (side == -1 and bar.low < take_at):
        return take_at, now + 60
    return None


def sample(data, known_signals, funding, dates):
    first, end = map(market.stamp, dates)
    active = []
    closed = []
    for bar in data.itertuples(index=False):
        now = int(bar.date.timestamp())
        if now < first:
            continue
        if now >= end:
            break
        signal = known_signals.get(now, 0)
        same_side = [t for t in active if t[0] == signal and now < t[2] + LIFETIME]
        if (
            signal
            and len(same_side) < 2
            and now - max((t[2] for t in same_side), default=0) > COOLDOWN
        ):
            active.append((signal, bar.open, now))
        still_active = []
        for side, basis, opened in active:
            close = bar_exit(side, basis, opened, now, bar)
            if not close:
                still_active.append((side, basis, opened))
                continue
            price, event = close
            qty = SIZE / basis
            gross = side * qty * (price - basis)
            turnover = qty * (price + basis)
            after = gross - turnover * FEE
            carry = sum(
                -side * qty * mark * rate
                for t, mark, rate in funding
                if opened < t < event
            )
            closed.append(
                (event, gross, after, after - turnover * EXTRA + carry, carry)
            )
        active = still_active
    return closed, len(active)


def main():
    data = {}
    carry = {}
    for coin in ("BTC", "ETH"):
        pair = coin + "USDT"
        data[coin] = market.parse_candles(f"klines-futures-{pair}-1m-*.zip", 1)
        marks = (
            market.parse_candles(f"markPriceKlines-futures-{pair}-1h-*.zip", 60)
            .set_index("date")
            .open
        )
        funding = market.funding(pair)
        carry[coin] = [
            (int(x.date.timestamp()), float(marks.at[x.date]), x.funding_rate)
            for x in funding.itertuples(index=False)
            if x.date in marks.index
        ]
    with (
        ZipFile(ROOT / "hb.zip") as archive,
        (ROOT / "round2/hummingbot-out.jsonl").open("w", encoding="utf-8") as out,
    ):
        for id_, name in CASES.items():
            relative = f"controllers/directional_trading/{name}.py"
            [path] = [n for n in archive.namelist() if n.endswith("/" + relative)]
            raw = archive.read(path)
            source = (
                f"https://github.com/hummingbot/hummingbot/blob/{SOURCE}/{relative}"
            )
            item = dict(id=id_, name=name, source_url=source)
            rows = []
            known = {}
            for coin, frame in data.items():
                candles = market.resample(frame, "3m")
                times = [int(t.timestamp()) + 180 for t in candles.date]
                known[coin] = dict(zip(times, map(int, signals(id_, candles))))
            for period, dates in market.WINDOWS.items():
                (btc, bo), (eth, eo) = [
                    sample(data[c], known[c], carry[c], dates) for c in ("BTC", "ETH")
                ]
                for future, ledger, unsettled in [
                    ("BTC/USDT perp", btc, bo),
                    ("ETH/USDT perp", eth, eo),
                    ("BTC + ETH perp", btc + eth, bo + eo),
                ]:
                    row = market.summary(
                        item,
                        future,
                        period,
                        "3m",
                        hashlib.sha256(raw).hexdigest(),
                        ledger,
                        unsettled,
                    )
                    row.update(
                        group="Hummingbot directional model · Binance",
                        exit="Modeled source triple barriers",
                        source_adaptation="Pinned indicator and executor rules, 3m closed signals, 1m next-open and barrier fills, 1× with historical funding",
                    )
                    rows.append(row)
            out.write(json.dumps(dict(id=id_, results=rows), allow_nan=False) + "\n")
            out.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        (ROOT / "round2/hummingbot-failure.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise
