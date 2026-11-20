"""Run selected native Python candidates inside the verified offline AppContainer."""

import hashlib
import json
import math
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deps"))

from fmz_native_python_worker import ReplayEnd, trusted_engine, unix

LOADER_SHA = "836dcbb307e38d64cb99c7de53733e07c4fa8319fc1d3be9e48583929e1e1208"


def replay(engine, item, feed, options):
    begin, end = (unix(feed[key]) * 1000 for key in ("start", "end"))
    raw = (ROOT / feed["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == feed["sha256"]
    history = json.loads(raw)
    requests = []

    def offline(url, body=None):
        split = urlparse(url)
        q = parse_qs(split.query)
        assert split.scheme in ("http", "https") and split.hostname == "q.fmz.com" and split.path == "/data/history" and body is None
        assert q["eid"] == ["Binance"] and q["symbol"] == [feed["symbol"]], url
        assert q["event"][0] in ("feed", "fill") and int(q["period"][0]) == feed["base_seconds"] * 1000, url
        start, stop = (int(q[key][0]) * 1000 for key in ("from", "to"))
        step = feed["base_seconds"] * 1000
        assert history["data"][0][0] <= start + step - 1 and history["data"][-1][0] >= stop - step, url
        requests.append(url)
        return json.dumps({**history, "data": [r for r in history["data"] if start <= r[0] <= stop]}).encode()

    original_time, original_sleep = time.time, time.sleep
    engine.httpGet = offline
    config = dict(eid="Binance", currency=feed["symbol"], balance=10000, stocks=0, fee=[.059, .059])
    runtime = dict(item["args"])
    task = f"""backtest
start: {feed['start']} 00:00:00
end: {feed['end']} 00:05:00
period: {feed['period']}
basePeriod: {feed['base']}
exchanges: {json.dumps([config])}
"""
    ctx = engine.VCtx(task, gApis=runtime)
    try:
        venue = runtime["exchange"]
        old_sleep = runtime["Sleep"]
        unix_ns = runtime["UnixNano"]
        assert abs(venue.GetTicker()["Time"] - begin) <= feed["base_seconds"] * 1000
        runtime["EnableLog"](False)
        calls = 0

        def sleep(ms):
            nonlocal calls
            calls += 1
            assert calls <= 6_000_000 and math.isfinite(ms) and ms >= 0, "Source exceeded bounded virtual polling"
            now = unix_ns() // 1_000_000
            if now + ms >= end - 10_000:
                if now < end - 10_000:
                    old_sleep(end - 10_000 - now)
                raise ReplayEnd()
            old_sleep(int(ms))

        runtime["Sleep"] = sleep
        if options.get("wall_sleep"):
            time.sleep = lambda sec: sleep(sec * 1000)
        if options.get("pandas_append"):
            import pandas as pd
            pd.DataFrame.append = lambda frame, row, ignore_index: pd.concat(
                [frame, pd.DataFrame([row])], ignore_index=ignore_index
            )
        # Order and branch semantics stay native. Source stdout and chart/log traffic are cosmetic.
        runtime["print"] = lambda *args, **kwargs: None
        trade_account = {}
        if options.get("market_cash_trace"):
            for name in ("Buy", "Sell"):
                place = getattr(venue, name)

                def log_market(price, amount, *args, place=place):
                    assert price == -1
                    before = venue.GetAccount()
                    id_ = place(price, amount, *args)
                    after = venue.GetAccount()
                    if id_:
                        trade_account[str(id_)] = (before, after)
                    return id_

                setattr(venue, name, log_market)
        for name in ("GetTicker", "GetRecords"):
            get = getattr(venue, name)

            def guard(*args, get=get, **kwargs):
                if unix_ns() // 1_000_000 >= end - 10_000:
                    raise ReplayEnd()
                return get(*args, **kwargs)

            setattr(venue, name, guard)
        stopped = False
        try:
            exec(compile(item["code"], f"catalogue-{item['id']}.py", "exec"), runtime)
            if "init" in runtime:
                runtime["init"]()
            runtime["main"]()
        except ReplayEnd:
            stopped = True
        current = unix_ns() // 1_000_000
        if not stopped and current < end - 10_000:
            old_sleep(end - 10_000 - current)
        snapshot_time = unix_ns() // 1_000_000
        assert end - 60_000 <= snapshot_time <= end, (snapshot_time, end)
        ticker = ctx.api(b"UnixNano")  # Read-only check that the engine clock remains available.
        assert ticker // 1_000_000 == snapshot_time
        account = venue.GetAccount()
        orders, since = [], begin
        for _ in range(100):
            page = venue.GetHistoryOrders(feed["symbol"], since, 100)
            assert all(since <= row["Time"] < end for row in page)
            orders.extend(page)
            if len(page) < 100:
                break
            since = max(row["Time"] for row in page) + 1
        else:
            raise ValueError("Order history page limit exceeded")
        resting = venue.GetOrders()
        seen = {row["Id"] for row in orders}
        orders.extend(row for row in resting if row["Id"] not in seen)
        return dict(requests=requests, calls=calls, last={"Time": snapshot_time}, account=account, orders=orders,
                    resting=len(resting), ended_early=not stopped, trade_account=trade_account)
    finally:
        time.sleep = original_sleep
        ctx.Join()
        time.time = original_time


def main():
    assert hashlib.sha256((ROOT / "official_fmz_python.py").read_bytes()).hexdigest() == LOADER_SHA
    engine = trusted_engine()
    worker_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    selected = {int(arg) for arg in sys.argv[1:]}
    receipt = ROOT / ("round4-native-python-" + "-".join(map(str, sorted(selected))) + ".jsonl")
    for job in json.loads((ROOT / "round4-native-python-jobs.json").read_bytes()):
        item, feed = job["item"], job["feed"]
        if item["id"] not in selected:
            continue
        meta = {"id": item["id"], "coin": feed["coin"], "start": feed["start"], "worker_sha256": worker_sha}
        try:
            row = {**meta, **replay(engine, item, feed, job["options"])}
        except Exception as exc:
            row = {**meta, "reason": f"{type(exc).__name__}: {exc}"[:650]}
        with receipt.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
