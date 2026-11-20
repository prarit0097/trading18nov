from pathlib import Path
import sys, os, traceback, importlib.util, json, hashlib, csv
from zipfile import ZipFile
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from functools import lru_cache

r = Path(__file__).resolve().parent
sys.path[:0] = [str(r / "jesse-deps"), str(r / "deps"), str(r)]
CASES = {
    5934: ("DUAL_THRUST", "15m", "futures", "2h"),
    5936: ("IFR2", "15m", "spot", None),
    5937: ("KDJstrategy", "1D", "spot", None),
    5939: ("MAGen", "15m", "futures", None),
    5942: ("SimpleBollinger", "1h", "spot", None),
    5943: ("TradingView_RSI", "15m", "futures", None),
    5944: ("TurtleRules", "1D", "futures", None),
}
W = {"Reference": ("2026-09-23", "2026-10-21"), "Later": ("2026-10-21", "2026-11-04")}
PERIOD_MS = {"15m": 900000, "1h": 3600000, "1D": 86400000}
FEE = 0.00059
EXTRA = 0.0003
START = 10000
IST = timezone(timedelta(hours=5, minutes=30))


def stamp(t):
    return int(datetime.fromisoformat(t).replace(tzinfo=IST).timestamp() * 1000)


@lru_cache(maxsize=4)
def load(kind, coin):
    import numpy as np

    values = []
    for f in sorted((r / "binance").glob(f"klines-{kind}-{coin}USDT-1m-*.zip")):
        with ZipFile(f) as data, data.open(data.namelist()[0]) as stream:
            for row in csv.reader(line.decode() for line in stream):
                if not row[0].isdigit():
                    continue
                t = int(row[0])
                t = t // 1000 if t >= 10**15 else t
                o, h, l, c, v = map(float, row[1:6])
                values.append((t, o, c, h, l, v))
    data = np.array(values, dtype=np.float64)
    assert (
        data.ndim == 2
        and (np.diff(data[:, 0]) == 60000).all()
        and (data[:, 5] > 0).all()
    ), (kind, coin)
    return data


def report(i, name, coin, label, tf, kind, h, rows, unsettled):
    sums = [0.0] * 3
    peaks = [START] * 3
    dd = [0.0] * 3
    ddp = [0.0] * 3
    wins = [0] * 3
    times = defaultdict(lambda: [0.0] * 3)
    for t, *vals in rows:
        for k, v in enumerate(vals):
            times[t][k] += v
            wins[k] += int(v > 1e-9)
    for legs in list(v for _, v in sorted(times.items())):
        for k, v in enumerate(legs):
            sums[k] += v
            equity = START + sums[k]
            peaks[k] = max(peaks[k], equity)
            dd[k] = max(dd[k], peaks[k] - equity)
            ddp[k] = max(ddp[k], (peaks[k] - equity) / peaks[k])
    market = coin if "+" in coin else coin + "/USDT"
    if kind == "futures":
        market += " perp"
    return dict(
        group="Jesse · Binance",
        id=i,
        name=name,
        market=market,
        period=label,
        exit="Source Jesse exits",
        venue="Binance USD-M perpetual" if kind == "futures" else "Binance spot",
        currency="USDT",
        source_sha256=h,
        source=f"https://github.com/jesse-ai/example-strategies/blob/7c91e0a37bf62165790120d730442e4f6eb00364/{name}/__init__.py",
        archive_interval=tf,
        interval=tf,
        funding_model="Native Jesse price-based study without funding cash flows",
        trades=len(rows),
        unsettled=unsettled,
        gross_wins=wins[0],
        fee_wins=wins[1],
        net_wins=wins[2],
        gross=sums[0],
        after_fees=sums[1],
        net=sums[2],
        fees=sums[0] - sums[1],
        execution=sums[1] - sums[2],
        gross_dd=dd[0],
        fee_dd=dd[1],
        net_dd=dd[2],
        gross_dd_pct=ddp[0],
        fee_dd_pct=ddp[1],
        net_dd_pct=ddp[2],
    )


def run(backtest, clss, tf, kind, anchor, dates, coin):
    import math

    candles = load(kind, coin)
    use_tf = PERIOD_MS[tf]
    start, end = map(stamp, dates)
    start = (start + use_tf - 1) // use_tf * use_tf
    end = end // use_tf * use_tf
    warmup = min(240, int((start - candles[0, 0]) // use_tf))
    assert warmup >= 40 and len(candles) > 0
    select = lambda first, last: candles[
        (candles[:, 0] >= first) & (candles[:, 0] < last)
    ]
    venue = "Binance Spot" if kind == "spot" else "Binance Perpetual Futures"
    symbol = f"{coin}-USDT"
    key = f"{venue}-{symbol}"
    warm_data = select(start - warmup * use_tf, start)
    test_data = select(start, end)
    assert (
        len(warm_data) * 60000 == warmup * use_tf
        and len(test_data) * 60000 == end - start
    )
    box = lambda a: {key: {"exchange": venue, "symbol": symbol, "candles": a}}
    config = dict(
        starting_balance=START,
        fee=FEE,
        type=kind,
        exchange=venue,
        warm_up_candles=warmup,
        annualization=365,
        futures_leverage=1,
        futures_leverage_mode="isolated",
    )
    route = dict(exchange=venue, symbol=symbol, timeframe=tf)
    response = backtest(
        config,
        [dict(route, strategy=clss)],
        [dict(route, timeframe=anchor)] if anchor else [],
        box(test_data),
        box(warm_data),
        fast_mode=True,
    )
    sample = []
    unsettled = 0
    for t in response.get("trades", []):
        if t["closed_at"] >= end - 60000:
            unsettled += 1
            continue
        assert start <= t["opened_at"] <= t["closed_at"] < end
        qty = abs(t["qty"])
        fee = float(t["fee"])
        close = float(t["PNL"])
        gross = close + fee
        turnover = qty * (t["entry_price"] + t["exit_price"])
        net = close - turnover * EXTRA
        assert all(math.isfinite(x) for x in (gross, close, net)) and qty > 0
        sample.append((int(t["closed_at"]), gross, close, net))
    return sample, unsettled


def main():
    import types

    research = types.ModuleType("jesse.research")
    research.__path__ = [str(r / "jesse-deps/jesse/research")]
    sys.modules["jesse.research"] = research
    spec = importlib.util.spec_from_file_location(
        "offline_jesse_backtest", r / "jesse-deps/jesse/research/backtest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    source = r / "jesse_sources"
    source.mkdir(exist_ok=True)
    picked = set(map(int, sys.argv[1:]))
    with (
        ZipFile(r / "example.zip") as archive,
        (r / "jesse-out.jsonl").open("w", encoding="utf-8") as out,
    ):
        for i, (name, tf, kind, anchor) in CASES.items():
            if picked and i not in picked:
                continue
            try:
                n = next(
                    p for p in archive.namelist() if p.endswith(f"/{name}/__init__.py")
                )
                raw = archive.read(n)
                h = hashlib.sha256(raw).hexdigest()
                file = source / (name + ".py")
                file.write_bytes(
                    raw.replace(b"self.capital", b"self.balance") if i == 5937 else raw
                )
                spec = importlib.util.spec_from_file_location(name, file)
                package = importlib.util.module_from_spec(spec)
                sys.modules[name] = package
                spec.loader.exec_module(package)
                clss = getattr(package, name)
                rows = []
                for p, dates in W.items():
                    btc, bopen = run(mod.backtest, clss, tf, kind, anchor, dates, "BTC")
                    eth, eopen = run(mod.backtest, clss, tf, kind, anchor, dates, "ETH")
                    for coin, closed, unsettled in [
                        ("BTC", btc, bopen),
                        ("ETH", eth, eopen),
                        ("BTC + ETH", btc + eth, bopen + eopen),
                    ]:
                        rows.append(
                            report(i, name, coin, p, tf, kind, h, closed, unsettled)
                        )
                rec = dict(id=i, results=rows)
            except Exception as exc:
                with (r / "jesse-run-errors.txt").open("a", encoding="utf-8") as log:
                    print("ID", i, file=log)
                    traceback.print_exc(file=log)
                rec = dict(
                    id=i,
                    reason=f"{type(exc).__name__}: {exc}".splitlines()[0].replace(
                        str(r), "scratch"
                    ),
                )
            out.write(json.dumps(rec, allow_nan=False) + "\n")
            out.flush()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        (r / "jesse-failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
