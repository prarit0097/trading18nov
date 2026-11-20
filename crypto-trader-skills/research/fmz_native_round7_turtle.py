"""Replay the archived Turtle signals using complete daily Binance candles."""

import argparse
import json
import re
from collections import deque
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import talib

from research.delta_pinets_catalogue import read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, stamp, summarize
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round6_audit import BASE, ROOT, digest
from research.fmz_native_round7 import display_settings, source

IDENT = 4860
DAY = 86400000
NOTES = (
    "Preserve the archived 20-day channel, 14-day ATR and 24-hour research frequency "
    "with the matched 1% stake. Evaluate completed daily bars. Model the native market "
    "and marketable-limit economics at the next traded opening observation."
)


def permits(close, ceiling, floor, prior, atr):
    entry = close > ceiling if not prior else close > prior + 0.5 * atr
    exit_ = bool(prior) and (close < floor or close < prior - 2 * atr)
    return entry, exit_


def replay(daily, intraday, feed, args):
    cap = args["DC_range"]
    risk = args["trade_percent"]
    assert (
        args["fresh_rete"] == 24
        and args["atrlength"] == 14
        and cap == 20
        and risk == 0.01
    )
    fields = daily["detail"]
    assert all(
        fields[k] == intraday["detail"][k]
        for k in ("quotePrecision", "basePrecision", "symbol")
    )
    quote = 10 ** fields["quotePrecision"]
    days, intervals = daily["data"], {row[0]: row for row in intraday["data"]}
    high, low, close = (np.array([r[i] / quote for r in days]) for i in (2, 3, 4))
    atr = talib.ATR(high, low, close, timeperiod=args["atrlength"])
    begin, end = (stamp(feed[tag]) * 1000 for tag in ("start", "end"))
    cash, stocks, last = EQUITY, 0.0, 0.0
    lots, trades, orders = deque(), [], []
    window = [i for i, row in enumerate(days) if begin <= row[0] < end]
    assert len(window) == (end - begin) // DAY and window[0] > cap
    for idx in window:
        now = days[idx][0]
        prior = idx - 1
        assert days[prior][0] + DAY == now
        # Both archive slices end two entries before the current record.
        ceil = max(high[prior - cap + 1 : prior - 1])
        floor = min(low[prior - cap // 2 + 1 : prior - 1])
        assert atr[prior] > 0
        entry, exit_ = permits(close[prior], ceil, floor, last, atr[prior])
        bar = intervals[now]
        if bar[5] <= 0:
            continue
        price = bar[1] / quote
        pre_trade_stocks = stocks
        if entry:
            value = (cash + stocks * close[prior]) * risk
            quantity = min(
                round(float(value / atr[prior]), 4), round(cash / (price + 100), 4)
            )
            turnover = quantity * price
            if (
                quantity >= fields["minQty"]
                and turnover >= fields["minNotional"]
                and cash >= (price + 10) * quantity
                and cash >= turnover * (1 + FEE)
            ):
                cash -= turnover * (1 + FEE)
                stocks += quantity
                last = price + 10
                lots.append((quantity, price))
                orders.append((now, "buy", quantity, price, last))
        if exit_:
            quantity = pre_trade_stocks
            turnover = quantity * price
            if quantity >= fields["minQty"] and turnover >= fields["minNotional"]:
                cash += turnover * (1 - FEE)
                stocks -= quantity
                orders.append((now, "sell", quantity, price, None))
                while quantity > 1e-9:
                    size, basis = lots.popleft()
                    fill = min(size, quantity)
                    gross = fill * (price - basis)
                    charge = fill * (price + basis)
                    fee_only = gross - charge * FEE
                    trades.append((now, gross, fee_only, fee_only - charge * EXECUTION))
                    quantity -= fill
                    if size - fill > 1e-9:
                        lots.appendleft((size - fill, basis))
            last = 0.0
    assert abs(stocks - sum(count for count, _ in lots)) < 1e-8
    assert (
        abs(
            cash
            + sum(n * p * (1 + FEE) for n, p in lots)
            - EQUITY
            - sum(r[2] for r in trades)
        )
        < 1e-7
    )
    return (
        trades,
        len(lots),
        {"orders": orders, "end_cash": cash, "end_stocks": stocks, "days": len(window)},
    )


def run(archive, target, daily_location, work, output):
    item = next(r for r in read(BASE)["disposition"] if r["id"] == IDENT)
    known = next(
        r
        for r in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
        if r["id"] == IDENT
    )
    with ZipFile(archive) as zipped:
        doc, code = source(zipped, item["source"])
    assert digest(doc) == known["document_sha256"]
    assert "max_price = df[-DC_range:-2]['High'].max()" in code
    assert "min_price = df[-int(DC_range/2):-2]['Low'].min()" in code
    assert "value = portfolio_value*trade_percent" in code
    settings = display_settings(work, IDENT, code)
    [args] = re.findall(r"(?m)^args:\s*(\[.*\])\s*$", code)
    settings["effective"] = {**settings["args"], **dict(json.loads(args))}
    native = read(ROOT / "fmz-native-extra-round6.json")
    inputs = {
        row["coin"]: row["feed"]["daily"]
        for row in native["snapshots"]
        if row["id"] == 4345
    }
    outcomes, results, evidence = {}, [], []
    for spec in read(target / "round5-native-python-jobs.json"):
        if spec["item"]["id"] != IDENT:
            continue
        feed = spec["feed"]
        d = inputs[feed["coin"]]
        raw_daily = (daily_location / d["file"]).read_bytes()
        raw_intraday = (target / feed["file"]).read_bytes()
        assert (
            digest(raw_daily) == d["sha256"] and digest(raw_intraday) == feed["sha256"]
        )
        trades, opened, details = replay(
            json.loads(raw_daily), json.loads(raw_intraday), feed, settings["effective"]
        )
        outcomes[feed["coin"], feed["start"]] = trades, opened
        evidence.append({**details, "daily": d, "intraday": feed})
    assert outcomes.keys() == KEYS and any(a or b for a, b in outcomes.values())
    for start, (_, window) in WINDOWS.items():
        b, bo = outcomes["BTC", start]
        e, eo = outcomes["ETH", start]
        for market, ledger, opened in (
            ("BTCUSDT", b, bo),
            ("ETHUSDT", e, eo),
            ("BTCUSDT + ETHUSDT", b + e, bo + eo),
        ):
            row = summarize(
                (
                    "FMZ Python · daily Turtle variant",
                    item["name"],
                    market + " spot",
                    "Archived Turtle exits",
                ),
                window,
                ledger,
                opened,
            )
            row.update(
                id=IDENT,
                source=item["source"],
                interval="1d",
                archive_interval="1d",
                quote_currency="USDT",
            )
            results.append(row)
    status = "Tested · FMZ daily Turtle variant" + (
        "" if any(r["trades"] for r in results) else ", no closes"
    )
    write(
        output,
        {
            "coverage": [[IDENT, status, NOTES]],
            "results": results,
            "source_sha256": known["document_sha256"],
            "settings": settings,
            "evidence": evidence,
            "talib_version": talib.__version__,
        },
    )
    print(IDENT, len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("archive", "target", "daily_location", "work", "output"):
        parser.add_argument(field, type=Path)
    run(**vars(parser.parse_args()))
