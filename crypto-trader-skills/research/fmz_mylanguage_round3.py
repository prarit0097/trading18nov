"""Confirmed-bar, linear-perpetual replays of selected archived FMZ MyLanguage rules."""

import argparse
import csv
import hashlib
import io
import math
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

import pandas as pd

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EXECUTION, FEE, NOTIONAL, stamp, summarize
from research.fmz_native_expanded_replay import BLOCKS
from research.fmz_native_round3 import BASELINE, WINDOWS

INTERVAL = {467: 1440, 621: 15, 1373: 1440, 1412: 5, 2520: 15, 2607: 60, 2608: 60, 4784: 1440}
NOTES = {
    467: "Insert the missing opening parenthesis in the documented typical-price calculation.",
    621: "Omit the notification-only hook and use the study's 15m chart interval.",
    1412: "Use the matching public AMA parameters and one fixed quote stake per reversal.",
    2520: "Use the study's 15m chart interval for the archived example.",
    2607: "Preserve the source's ATR-channel exits and track high and low after the entry signal.",
    2608: "Apply the public channel settings. Replace the original inverse dated lot with a fixed quote stake.",
    4784: "Use matched public absolute price thresholds and retain the source's open-price stop reference.",
}
DOC = "https://www.fmz.com/doc/9480"


def source_items(archive):
    pending = [r for r in read(BASELINE)["disposition"] if not r["status"].startswith("Tested")]
    items = {}
    with ZipFile(archive) as fmz:
        for row in pending:
            if "Archive contains pascal " not in row["reason"]:
                continue
            name = unquote(row["source"].split(f"/{FMZ_REF}/", 1)[1])
            raw = fmz.read(f"strategies-{FMZ_REF}/{name}")
            [code] = [code for tag, code in BLOCKS.findall(raw.decode("utf-8")) if tag.strip().lower() == "pascal"]
            items[row["id"]] = {**row, "code": code, "document_sha256": hashlib.sha256(raw).hexdigest()}
    assert INTERVAL.keys() <= items.keys()
    return items


def inputs(data, symbol, registry):
    evidence = {}

    def verify(path):
        raw = path.read_bytes()
        meta = registry[path.name]
        assert hashlib.sha256(raw).hexdigest() == meta["sha256_or_error"], path
        evidence[path.name] = meta
        return raw

    def csv_rows(prefix):
        for path in sorted(data.glob(prefix + "*.zip")):
            with ZipFile(io.BytesIO(verify(path))) as z:
                [name] = z.namelist()
                with z.open(name) as stream:
                    yield from (r for r in csv.reader(io.TextIOWrapper(stream, encoding="ascii")) if r[0].isdigit())

    rows = [tuple(map(float, r[:6])) for r in csv_rows(f"klines-futures-{symbol}-1m-")]
    frame = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    times = frame.pop("time").astype("int64")
    assert times.diff().iloc[1:].eq(60_000).all()
    assert ((frame.low > 0) & (frame.low <= frame[["open", "close"]].min(axis=1))).all()
    assert ((frame.high >= frame[["open", "close"]].max(axis=1)) & (frame.volume >= 0)).all()
    frame.index = pd.to_datetime(times, unit="ms", utc=True)
    marks = {int(r[0]) // 1000: float(r[1]) for r in csv_rows(f"markPriceKlines-futures-{symbol}-1h-")}
    rates = {round(int(r[0]) / 28800000) * 28800: float(r[2]) for r in csv_rows(f"fundingRate-futures-{symbol}-")}
    nov = data / f"funding-{symbol}-nov.json"
    verify(nov)
    rates.update({round(r["fundingTime"] / 28800000) * 28800: float(r["fundingRate"]) for r in read(nov)})
    stamps = range(stamp("2026-09-23") // 28800 * 28800, stamp("2026-11-04") // 28800 * 28800 + 28800, 28800)
    return frame, [(t, marks[t], rates[t]) for t in stamps], evidence


def bars(frame, minutes):
    grouped = frame.resample(f"{minutes}min")
    out = grouped.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out[grouped.size().eq(minutes)]


def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()


def dma(close, period, faster, slower):
    ratio = close.diff(period).abs() / close.diff().abs().rolling(period).sum()
    alphas = (ratio * (2 / (faster + 1) - 2 / (slower + 1)) + 2 / (slower + 1)) ** 2
    values, last = [], None
    for price, alpha in zip(close, alphas):
        if not 0 < alpha < 1:
            values.append(math.nan)
            continue
        last = price if last is None else last + alpha * (price - last)
        values.append(last)
    return ema(pd.Series(values, index=close.index), 2)


def rules(id_, df, args):
    h, low, c = (df[k] for k in ("high", "low", "close"))
    out = df.copy()
    out["long"] = out["short"] = False
    out["close_long"] = out["close_short"] = False
    if id_ == 467:
        typical = ema((h + low + c) / 3, 10)
        shift = ema(h - c, 10)
        out["long"], out["short"] = c > typical + shift, c < typical - shift
    elif id_ == 621:
        out["short"] = c > h.shift(1).rolling(10, min_periods=1).max()
        out["long"] = c < low.shift(1).rolling(15, min_periods=1).min()
    elif id_ == 1373:
        dx = ema((h + low + c) / 3, 21)
        base = ema(dx, 21)
        out["long"], out["short"] = (c > dx) & (dx < base * 1.05), (c < dx) & (dx > base / 1.05)
    elif id_ == 1412:
        a = dma(c, args["N"], args["N1"], args["N2"])
        b = dma(c, args["M"], args["M1"], args["M2"])
        out["long"], out["short"] = (a.shift() < b.shift()) & (a > b), (a.shift() > b.shift()) & (a < b)
    elif id_ == 2520:
        avg = c.rolling(5).mean()
        out["long"], out["short"] = c > h.rolling(5).mean(), c < low.rolling(5).mean()
        out["close_long"], out["close_short"] = c < avg, c > avg
    elif id_ in (2607, 2608):
        n, m = (200, 4) if id_ == 2607 else (args["N"], args["M"])
        tr = pd.concat((h - low, (c.shift() - h).abs(), (c.shift() - low).abs()), axis=1).max(axis=1, skipna=False)
        channel = m * tr.rolling(n).mean()
        avg = c.rolling(n).mean()
        out["long"], out["short"] = h >= h.rolling(n, min_periods=1).max(), low <= low.rolling(n, min_periods=1).min()
        out["close_long"] = (h >= h.rolling(m * n, min_periods=1).max()) | (c <= avg + channel)
        out["close_short"] = (low <= low.rolling(m * n, min_periods=1).min()) | (c >= avg - channel)
    elif id_ == 4784:
        fast, slow = c.rolling(10).mean(), c.rolling(30).mean()
        out["long"] = (c.shift() < args["MMD"]) | ((fast > slow) & (fast.shift() <= slow.shift()))
        out["short"] = (c.shift() > args["HGH"]) | ((fast < slow) & (fast.shift() >= slow.shift()))
        out["close_long"], out["close_short"] = out["short"], out["long"]
    else:
        raise ValueError(id_)
    return out


def order(id_, bar, side, signal, highest, lowest, args):
    if id_ == 4784:
        if not side:
            # BK and SK are in this order in the archive, with one permitted signal per bar.
            return 1 if bar.long else -1 if bar.short else side
        stop = args["STOPLOSS"] * 0.01
        if side == 1 and (bar.close_long or bar.low <= signal * (1 - stop)):
            return 0
        if side == -1 and (bar.close_short or bar.high >= signal * (1 + stop)):
            return 0
        return side
    # Source order is significant when a reversal and a close both qualify.
    for cmd, okay in ([(1, bar.long), (-1, bar.short)] if id_ != 621 else [(-1, bar.short), (1, bar.long)]):
        if okay and side != cmd:
            return cmd
    if id_ in (2607, 2608):
        n, stop = (4, 0.02) if id_ == 2607 else (args["M"], args["SLOSS"] * 0.01)
        if side == 1 and ((bar.close_long and highest >= signal * (1 + n * stop)) or bar.close <= signal * (1 - stop)):
            return 0
        if side == -1 and ((bar.close_short and lowest <= signal * (1 - n * stop)) or bar.close >= signal * (1 + stop)):
            return 0
    elif side == 1 and bar.close_long or side == -1 and bar.close_short:
        return 0
    return side


def simulate(id_, df, raw, funding, first, end, args):
    ledger, evidence, active = [], [], None
    side, signal = 0, 0.0
    highest, lowest = -math.inf, math.inf
    step = INTERVAL[id_] * 60
    # Store the original minute opens, including those from partially observed boundary bars.
    prices = raw.loc[pd.Timestamp(first, unit="s", tz="UTC"):pd.Timestamp(end - 60, unit="s", tz="UTC")]
    minute = dict(zip(prices.index.asi8 // 10**9, zip(prices.open, prices.volume)))
    first_bar = (first + step - 1) // step * step
    for bar in df.itertuples():
        open_time = int(bar.Index.timestamp())
        fill = open_time + step
        if open_time < first_bar or fill >= end:
            continue
        if side:
            highest, lowest = max(highest, bar.high), min(lowest, bar.low)
        target = order(id_, bar, side, signal, highest, lowest, args)
        if target == side:
            continue
        price, volume = minute[fill]
        if volume <= 0:
            raise ValueError("The next-minute bar had no observed trade")
        if active:
            entry_time, basis, qty = active
            gross = side * qty * (price - basis)
            turnover = qty * (price + basis)
            after_fees = gross - turnover * FEE
            # Existing positions held entering a funding boundary carry the funding charge before exit.
            carry = sum(-side * qty * mark * rate for t, mark, rate in funding if entry_time < t <= fill)
            ledger.append((fill, gross, after_fees, after_fees - turnover * EXECUTION + carry, carry))
            evidence.append({"side": side, "qty": qty, "entry": entry_time, "exit": fill, "entry_price": basis,
                                 "exit_price": price, "gross": gross, "funding": carry})
        active = (fill, price, NOTIONAL / price) if target else None
        # BKPRICE/SKPRICE use the signal candle close. 4784 stores the next candle open with VALUEWHEN.
        signal = price if id_ == 4784 else bar.close
        side, highest, lowest = target, -math.inf, math.inf
    return ledger, evidence, int(active is not None)


def run(scratch, output):
    items = source_items(scratch / "fmz.zip")
    market_path = scratch / "nonpine" / "binance"
    registry = read(market_path / "manifest.json")
    markets = {coin: inputs(market_path, coin + "USDT", registry) for coin in ("BTC", "ETH")}
    cached = {(coin, interval): bars(raw, interval) for coin, (raw, _, _) in markets.items() for interval in set(INTERVAL.values())}
    params = {r["id"]: r for r in read(scratch / "round3-native" / "round3-parameter-checks.json")}
    results, coverage, evidence = [], [], []
    unresolved = {
        262: "Published N, KS and KX recovered. The original weekly inverse contract and unrestricted repeated entries need their own ledger.",
        485: "Public RSI filter Y recovered. Source computes order size from inverse-contract equity and price.",
        492: "Original BitMEX inverse exposure and pyramiding depend on contract equity and unit.",
        1201: "Needs the historic Argus Bitcoin news-score series.",
        1340: "Public N and SLOSS recovered. Archived cumulative order instructions need inverse venue sizing and position accounting.",
        1353: "SETSIGPRICETYPE with NEW_ORDER needs its historical quote/order execution semantics.",
        2089: "Public N1, N2 and SLOSS recovered. Keep separate inverse long and short inventory under source settings.",
        2499: "Archived China commodity futures contract and strategy settings need that instrument's historical terms.",
        4392: "Public len recovered. Inverse equity-based position size depends on contract specifications.",
        4515: "Published page unavailable. Missing limit and scaling parameters and 50x margin/liquidation model.",
        4736: "Published page unavailable. MULTSIG and 50x scaling need same-instrument intrabar order and margin ledger.",
        5695: "Public thresholds recovered. Position sizing needs inverse contract equity and lot conversion.",
        5779: "Public RATIO recovered. Source uses tick-level MULTSIG and stateful Turtle pyramiding.",
        5780: "Public long initial amount is zero. Shown source is a single conditional entry with no complete grid closure.",
    }
    for id_, item in items.items():
        if id_ not in INTERVAL:
            coverage.append([id_, item["status"], unresolved.get(id_, item["reason"])])
            continue
        code = item["code"]
        assert "AUTOFILTER" in code or id_ == 1412, id_
        if id_ == 467:
            assert "DX:=H+L+C)/3;" in code
        args = params.get(id_, {}).get("args", {})
        tested = False
        for start, (end, period) in WINDOWS.items():
            outcomes = {}
            for coin, (raw, funding, _) in markets.items():
                df = rules(id_, cached[coin, INTERVAL[id_]], args)
                trades, orders, open_count = simulate(id_, df, raw, funding, stamp(start), stamp(end), args)
                outcomes[coin] = (trades, open_count)
                evidence.append({"id": id_, "coin": coin, "start": start, "trades": orders, "open_count": open_count})
            btc, ob = outcomes["BTC"]
            eth, oe = outcomes["ETH"]
            tested |= bool(btc or eth)
            for scope, ledger, opened in (("BTCUSDT", btc, ob), ("ETHUSDT", eth, oe), ("BTCUSDT + ETHUSDT", btc + eth, ob + oe)):
                label = "FMZ MyLanguage · Linear bar variant"
                row = summarize((label, item["name"], scope + " perp", "Archived model rules, next open"), period, [trade[:4] for trade in ledger], opened)
                row.update(id=id_, source=item["source"], source_sha256=item["document_sha256"], interval=f'{INTERVAL[id_]}m',
                           market_data="Binance USD-M candles and funding", quote_currency="USDT",
                           funding=sum(t[4] for t in ledger), adaptation=NOTES.get(id_, ""))
                row["execution"] += row["funding"]
                results.append(row)
        status = "Tested · FMZ MyLanguage bar variant" if tested else "Tested · FMZ MyLanguage bar variant, no closes"
        coverage.append([id_, status, "Confirmed-bar translation on Binance USD-M perpetuals. " + NOTES.get(id_, "")])
    write(output, {
        "baseline": "f66984c", "source_revision": FMZ_REF, "language_reference": DOC,
        "coverage": coverage, "public_parameters": [r for i, r in params.items() if i in items],
        "markets": {c: v[2] for c, v in markets.items()}, "closed_lots": evidence, "results": results,
    })
    print(len(coverage), "MyLanguage dispositions and", len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.scratch, args.output)
