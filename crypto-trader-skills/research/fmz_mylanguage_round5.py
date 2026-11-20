"""Replay pinned stateful MyLanguage rules on confirmed Binance perpetual bars."""

import argparse
import math
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, NOTIONAL, stamp, summarize
from research.fmz_mylanguage_round3 import DOC, bars, ema, inputs, source_items
from research.fmz_mylanguage_round4 import cross_down, cross_up, true_range
from research.fmz_native_round3 import WINDOWS
from research.fmz_native_round4 import sha

HERE = Path(__file__).parent
SPECS = {
    492: (1440, {"ratio": .01}, 1, "Use the 26-day ATR and prior 20-day channels. Size a linear base unit from one percent of equity divided by ATR."),
    1007: (60, {"LENGE": 260, "percent": 5}, 1, "Replace inverse dated contracts with one fixed 1,000 USDT lot per side. Evaluate UTC daily anchors and preserve the source's signed volume comparisons."),
    4515: (5, {"BLD": 1, "FX": 2, "TC": .001, "XX": 1, "CJ": 2, "CJ2": 2, "FB": 4}, 50,
           "Use archived BLD=1 and archived table defaults for scaling and exits. Evaluate the first eligible instruction per confirmed bar."),
    4736: (360, {"N": .002, "XX": 1, "limit": 100}, 50,
           "Use the archived 6h WMA strategy with the table's 0.002 base stake and numeric true multiplier of one. Use a confirmed-bar first-action substitute for MULTSIG."),
    5779: (1440, {"ratio": .01}, 1, "Use prior 20/55-day breakouts, last-exit state and the 10-day opposite channel. Replace MULTSIG with a confirmed-bar first-action rule."),
    5780: (15, {"ktkc": 10, "dtkc": 0, "y": .02, "s": .02, "jia": 1, "jian": 1}, 1,
           "Use the matching public short-side grid defaults and evaluate once per 15m closed bar. Convert each source lot to 0.001 base units."),
}


def wma(series, length):
    weights = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda samples: np.dot(samples, weights) / weights.sum(), raw=True)


def features(id_, frame, args):
    f = frame.copy()
    o, h, l, c = (f[x] for x in ("open", "high", "low", "close"))
    tr = true_range(h, l, c)
    if id_ in (492, 5779):
        f["atr"] = tr.rolling(26 if id_ == 492 else 20).mean()
        for n in (10, 20, 55):
            # MyLanguage HV and LV exclude the current bar.
            hh, ll = h.shift().rolling(n, min_periods=1).max(), l.shift().rolling(n, min_periods=1).min()
            f[f"above_{n}"] = cross_up(h if n == 10 else c, hh)
            f[f"below_{n}"] = cross_down(l if n == 10 else c, ll)
    elif id_ == 1007:
        n = args["LENGE"]
        anchor = o.groupby(o.index.normalize()).transform("first")
        upper = (h.shift() - c.shift() + anchor).rolling(n, min_periods=1).max()
        lower = (l.shift() - c.shift() + anchor).rolling(n, min_periods=1).min()
        ma = ema(c.shift(), 240)
        expanded = (h - l) > (h - l).shift()
        f["long"] = (c.shift() > ma) & (((h + l) / 2 > h.shift()) & expanded).shift(fill_value=False) & (c.shift() > upper.shift())
        f["short"] = (c.shift() < ma) & (((h + l) / 2 < l.shift()) & expanded).shift(fill_value=False) & (c.shift() < lower.shift())
        f["prior_high"], f["prior_low"], f["prior_close"] = h.shift(), l.shift(), c.shift()
    elif id_ == 4515:
        f["atr"] = wma(tr, 26)
        midpoint = c.rolling(26).mean()
        reference = midpoint if args["BLD"] else midpoint - 2 * c.rolling(26).std(ddof=1)
        f["long"], f["short"] = cross_up(c, reference), cross_down(c, reference)
    elif id_ == 4736:
        f["atr"] = wma(tr, 10)
        fast, slow = wma(c, 10).shift(), wma(c, 20).shift()
        f["long"], f["short"] = fast > slow, fast < slow
    return f


class Book:
    def __init__(self, funding, leverage):
        self.funding = funding
        self.leverage = leverage
        self.inventory = deque()
        self.settled = []
        self.orders = []
        self.cash = EQUITY
        self.side = 0
        self.rejected = 0

    @property
    def qty(self):
        return sum(lot[2] for lot in self.inventory)

    @property
    def average(self):
        return sum(price * size for _, price, size in self.inventory) / self.qty if self.side else 0

    @property
    def last(self):
        return self.inventory[-1][1] if self.side else 0

    def carry(self, start, end, qty):
        return sum(-self.side * qty * mark * rate for at, mark, rate in self.funding if start < at <= end)

    def equity(self, price, at):
        return self.cash + sum(self.side * size * (price - basis) + self.carry(entry, at, size)
                               for entry, basis, size in self.inventory)

    def open(self, t, price, qty, side, signal):
        assert side in (-1, 1) and self.side in (0, side) and math.isfinite(qty) and qty > 0
        fee = qty * price * FEE
        if (self.qty + qty) * price / self.leverage + fee > self.equity(price, t):
            self.rejected += 1
            return False
        self.side = side
        self.cash -= fee
        self.inventory.append((t, price, qty))
        self.orders.append([t, side, qty, price, signal])
        return True

    def close(self, t, price, qty, signal):
        assert self.side and 0 < qty <= self.qty + 1e-12
        self.orders.append([t, -self.side, qty, price, signal])
        while qty > 1e-12:
            entry, basis, size = self.inventory.popleft()
            take = min(qty, size)
            gross = self.side * take * (price - basis)
            fee = take * (price + basis) * FEE
            costs = take * (price + basis) * EXECUTION
            funding = self.carry(entry, t, take)
            self.cash += gross - take * price * FEE + funding
            self.settled.append([self.side, entry, t, basis, price, take, gross, fee, costs, funding])
            qty -= take
            if size - take > 1e-12:
                self.inventory.appendleft((entry, basis, size - take))
        if not self.inventory:
            self.side = 0

    def verify(self, as_of):
        closed_equity = EQUITY + sum(gross - fee + carry for *_, gross, fee, _, carry in self.settled)
        open_fee = sum(size * basis * FEE for _, basis, size in self.inventory)
        assert abs(self.cash - (closed_equity - open_fee)) < 1e-7
        assert all(a[0] <= b[0] for a, b in zip(self.orders, self.orders[1:]))
        assert abs(sum(side * size for _, side, size, *_ in self.orders) - self.side * self.qty) < 1e-10
        return {"orders": len(self.orders), "closed_fills": self.settled, "open_lots": list(self.inventory),
                "final_side": self.side, "rejects": self.rejected, "ending_cash": self.cash,
                "unsettled_funding": sum(self.carry(t, as_of, size) for t, _, size in self.inventory)}


def replay(id_, frame, raw, funding, first, end, args, interval, leverage):
    book = Book(funding, leverage)
    step = interval * 60
    eligible = frame.loc[pd.Timestamp(first, unit="s", tz="UTC"):pd.Timestamp(end - step - 1, unit="s", tz="UTC")]
    failures, anchor, consecutive, previous = True, 1.0, 0, None
    lower = upper = long_exit = short_exit = 0.0
    factor = 1.0
    entry_at = 0
    minimum_marked_equity = EQUITY
    for bar in eligible.itertuples():
        t = int(bar.Index.timestamp()) + step
        fill = raw.loc[pd.Timestamp(t, unit="s", tz="UTC")]
        assert fill.volume > 0 and fill.open > 0
        price, side, qty = float(fill.open), book.side, book.qty
        adverse_price = bar.low if side == 1 else bar.high
        if side:
            adverse_equity = book.equity(adverse_price, t)
            minimum_marked_equity = min(minimum_marked_equity, adverse_equity)
            assert adverse_equity > .01 * adverse_price * qty, "Position crosses the variant maintenance boundary"
        if id_ in (492, 5779):
            limit, keep_state = 10, id_ == 5779
            if not math.isfinite(bar.atr) or bar.atr <= 0:
                continue
            unit = args["ratio"] * max(0, book.equity(bar.close, t)) / bar.atr
            if not unit:
                continue
            short_breakout = not keep_state or failures
            if not side:
                signal = 1 if (short_breakout and bar.above_20) or (keep_state and bar.above_55) else (
                    -1 if (short_breakout and bar.below_20) or (keep_state and bar.below_55) else 0)
                if signal and book.open(t, price, unit, signal, "breakout"):
                    previous, consecutive = "breakout", 1
            elif side * (bar.close - book.last) >= .5 * bar.atr and qty < 4 * unit and (previous != "scale" or consecutive < limit):
                if book.open(t, price, unit, side, "scale"):
                    consecutive = consecutive + 1 if previous == "scale" else 1
                    previous = "scale"
            else:
                stop = side * (bar.close - book.last) <= -2 * bar.atr
                channel = bar.below_10 if side == 1 else bar.above_10
                if stop or channel:
                    book.close(t, price, qty, "stop" if stop else "opposite channel")
                    failures, previous, consecutive = stop, None, 0
        elif id_ == 1007:
            # Source volume is nonnegative. The archived short guard compares against -1.
            if side != 1 and bar.long:
                lower = bar.low
                if side == -1:
                    book.close(t, price, qty, "long reversal close")
                if book.open(t, price, NOTIONAL / price, 1, "long reversal open"):
                    entry_at = t
            elif bar.short:
                upper = bar.high
                if side == 1:
                    book.close(t, price, qty, "short reversal close")
                if side != -1 and book.open(t, price, NOTIONAL / price, -1, "short reversal open"):
                    entry_at = t
            if side:
                if side == 1:
                    lower = max(lower, bar.low)
                else:
                    upper = min(upper, bar.high)
                upper, lower = min(upper, bar.prior_high), max(lower, bar.prior_low)
                factor = max(.5, factor - .1)
                next_long, next_short = lower - bar.open * .06 * factor, upper + bar.open * .06 * factor
                long_stop = next_long > 0 and bar.close <= next_long and bar.prior_close >= long_exit
                short_stop = next_short > 0 and bar.close >= next_short and bar.prior_close <= short_exit
                if t > entry_at and book.side == side and (long_stop if side == 1 else short_stop):
                    book.close(t, price, qty, "trailing cross")
                long_exit, short_exit = next_long, next_short
            else:
                factor = 1.0
        elif id_ in (4515, 4736):
            first_size = args["TC"] if id_ == 4515 else args["N"]
            scale = args.get("CJ", .1) * bar.atr
            take_profit = args.get("CJ2", .1) * bar.atr
            allowed = args.get("FB", args.get("limit"))
            if not side and (bar.long or bar.short):
                if book.open(t, price, first_size, 1 if bar.long else -1, "entry"):
                    previous, consecutive = "entry", 1
            elif side and side * (bar.close - book.last) < -scale and previous in ("entry", "scale") and (previous != "scale" or consecutive < allowed):
                if book.open(t, price, round(qty * args["XX"], 3), side, "scale"):
                    consecutive = consecutive + 1 if previous == "scale" else 1
                    previous = "scale"
            elif side:
                gain = side * (bar.close - book.average)
                trend_stop = id_ == 4736 and (bar.short if side == 1 else bar.long)
                if gain > take_profit or trend_stop:
                    book.close(t, price, qty, "target or trend exit")
                    previous, consecutive = None, 0
                elif id_ == 4515 and qty >= .008 and gain > take_profit / 2:
                    book.close(t, price, .001, "partial target")
                    previous, consecutive = "partial target", 1
        else:
            assert id_ == 5780 and args["dtkc"] == 0
            if not side:
                if book.open(t, price, args["ktkc"] * .001, -1, "initial short"):
                    anchor = bar.close
            elif bar.close < anchor / (1 + args["y"]):
                book.close(t, price, min(qty, args["jian"] * .001), "reduce short")
                anchor = bar.close
            elif bar.close > anchor * (1 + args["s"]):
                if book.open(t, price, args["jia"] * .001, -1, "increase short"):
                    anchor = bar.close
    result = {**book.verify(end), "minimum_marked_equity": minimum_marked_equity}
    fills = [(t, gross, gross - fee, gross - fee - cost + carry, carry)
             for _, _, t, _, _, _, gross, fee, cost, carry in book.settled]
    return fills, int(bool(book.side)), result


def run(scratch, output):
    entries = source_items(scratch / "fmz.zip")
    baseline = {r["id"]: r for r in read(HERE / "remaining-backtest-round4-coverage.json")["disposition"]
                if not r["status"].startswith("Tested")}
    audit = {r["id"]: r for r in read(HERE / "fmz-native-round4-coverage.json")["disposition"]}
    assert SPECS.keys() <= entries.keys() & baseline.keys()
    directory = scratch / "nonpine" / "binance"
    manifest = read(directory / "manifest.json")
    markets = {coin: inputs(directory, coin + "USDT", manifest) for coin in ("BTC", "ETH")}
    prior = read(scratch / "round3-native" / "round3-parameter-checks.json")
    additional = read(scratch / "round4" / "native-params" / "receipt.json")
    metadata = {r["id"]: r for r in prior + additional}
    results, coverage, evidence, specs = [], [], [], []
    for id_, (interval, args, leverage, notes) in SPECS.items():
        item = entries[id_]
        assert audit[id_]["document_sha256"] == item["document_sha256"]
        args_from_public = metadata.get(id_, {}).get("args", {})
        assert all(key not in args or args[key] == value for key, value in args_from_public.items())
        specs.append({"id": id_, "source": item["source"], "document_sha256": item["document_sha256"],
                      "formula_sha256": sha(item["code"].encode()), "args": args, "interval_minutes": interval,
                      "leverage": leverage, "public_parameters": metadata.get(id_, {})})
        frames = {coin: features(id_, bars(market[0], interval), args) for coin, market in markets.items()}
        closes = positions = 0
        start_results = []
        for start, (end, window) in WINDOWS.items():
            runs = {}
            for coin, (raw, funding, _) in markets.items():
                fills, opened, receipt = replay(id_, frames[coin], raw, funding, stamp(start), stamp(end), args, interval, leverage)
                evidence.append({"id": id_, "coin": coin, "start": start, **receipt})
                closes += len(fills)
                positions += opened
                runs[coin] = fills, opened
            btc, ob = runs["BTC"]
            eth, oe = runs["ETH"]
            for label, fills, opened in (("BTCUSDT", btc, ob), ("ETHUSDT", eth, oe), ("BTCUSDT + ETHUSDT", btc + eth, ob + oe)):
                row = summarize(("FMZ MyLanguage · Confirmed-bar linear variant", item["name"], label + " perp",
                                 "Source signal and position rules"), window, [f[:4] for f in fills], opened)
                row.update(id=id_, source=item["source"], source_sha256=item["document_sha256"], interval=f"{interval}m",
                           starting_equity=EQUITY, adaptation=notes, market_data="Binance USD-M candles and funding",
                           quote_currency="USDT", funding=sum(f[4] for f in fills))
                row["execution"] += row["funding"]
                start_results.append(row)
        if not (closes or positions):
            coverage.append([id_, "FMZ native offline replay pending", "No qualifying position in the two confirmed-bar windows"])
            continue
        results.extend(start_results)
        coverage.append([id_, "Tested · FMZ MyLanguage linear variant" + ("" if closes else ", no closes"), notes])
    write(output, {"baseline": "8fc965fe", "source_revision": FMZ_REF, "language_reference": DOC, "specs": specs,
                   "market": {coin: value[2] for coin, value in markets.items()},
                   "fill_fields": ["side", "entry", "exit", "entry_price", "exit_price", "size", "gross", "fees", "execution", "funding"],
                   "coverage": coverage, "order_evidence": evidence, "results": results})
    print(len(coverage), "MyLanguage trials,", len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    run(options.scratch, options.output)
