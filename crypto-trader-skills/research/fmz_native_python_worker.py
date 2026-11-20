"""Run screened native Python source inside the no-network Windows AppContainer."""

import hashlib
import importlib.util
import json
import pathlib
import sys
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).absolute().parent
ENGINE_REV = "b6cd4d12f15d88c48d3b416510ca9e48d2e46da7"
DLL_SHA = "504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0"
DLL = ROOT / "depends" / "backtest_py_windows_64bit.so"


class ReplayEnd(BaseException):
    pass


def unix(day):
    return int(datetime.fromisoformat(day + "T00:00:00+05:30").timestamp())


def trusted_engine():
    assert hashlib.sha256(DLL.read_bytes()).hexdigest() == DLL_SHA
    spec = importlib.util.spec_from_file_location("fmz", ROOT / "official_fmz_python.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    sys.modules["fmz"] = engine
    return engine


def replay(engine, trial):
    item, feed, cfg = (trial[k] for k in ("item", "feed", "cfg"))
    beginning, end = (unix(feed[key]) * 1000 for key in ("start", "end"))
    archive = (ROOT / feed["file"]).read_bytes()
    assert hashlib.sha256(archive).hexdigest() == feed["sha256"]
    history = json.loads(archive)
    requests = []

    def offline(url, body=None):
        split = urlparse(url)
        assert split.hostname == "q.fmz.com" and split.path == "/data/history" and body is None, url
        query = parse_qs(split.query)
        assert query["eid"] == [feed["eid"]] and query["symbol"] == [feed["symbol"]], url
        assert query["event"] == ["feed"] and query["period"] == [str(feed["base_seconds"] * 1000)], url
        start, stop = (int(query[k][0]) * 1000 for k in ("from", "to"))
        assert history["data"][0][0] <= start and history["data"][-1][0] >= stop - feed["base_seconds"] * 1000, url
        requests.append(url)
        return json.dumps({**history, "data": [r for r in history["data"] if start <= r[0] <= stop]}).encode()

    engine.httpGet = offline
    runtime = dict(item["args"])
    config = dict(eid=feed["eid"], currency=feed["symbol"], balance=cfg["balance"], stocks=0,
                  fee=[cfg["fee"] * 100, cfg["fee"] * 100])
    task = f"""backtest
start: {feed['start']} 00:00:00
end: {feed['end']} 00:05:00
period: {feed['period']}
basePeriod: {feed['base']}
exchanges: {json.dumps([config])}
"""
    host_time = time.time
    ctx = engine.VCtx(task, gApis=runtime)
    try:
        exchange = runtime["exchange"]
        assert exchange.GetTicker()["Time"] == beginning
        if not getattr(exchange, "GetMinStock", None):
            exchange.GetMinStock = lambda: history["detail"]["minQty"]
        old_sleep = runtime["Sleep"]
        calls = 0

        def sleep(ms):
            nonlocal calls
            calls += 1
            assert calls <= 200_000 and 0 <= ms, "Source exceeded supported polling budget"
            now = runtime["UnixNano"]() // 1_000_000
            if now + ms >= end - 10_000:
                if now < end - 10_000:
                    old_sleep(end - 10_000 - now)
                raise ReplayEnd()
            old_sleep(ms)

        runtime["Sleep"] = sleep
        stopped = False
        try:
            exec(compile(item["code"], f"catalogue-{trial['id']}.py", "exec"), runtime)
            if "init" in runtime:
                runtime["init"]()
            runtime["main"]()
        except ReplayEnd:
            stopped = True
        if not stopped:
            ms = end - 10_000 - runtime["UnixNano"]() // 1_000_000
            if ms > 0:
                old_sleep(ms)
        last = exchange.GetTicker()
        assert end - 60_000 <= last["Time"] <= end
        account = exchange.GetAccount()
        orders, since = [], beginning
        for _ in range(100):
            page = exchange.GetHistoryOrders(feed["symbol"], since, 100)
            assert all(since <= o["Time"] < end for o in page)
            orders.extend(page)
            if len(page) < 100:
                break
            since = max(o["Time"] for o in page) + 1
        else:
            raise ValueError("History page limit exceeded")
        resting = exchange.GetOrders()
        seen = {o["Id"] for o in orders}
        orders.extend(o for o in resting if o["Id"] not in seen)
        return dict(requests=requests, calls=calls, skipped=0, last=last, account=account, orders=orders,
                    resting=len(resting), endedEarly=not stopped)
    finally:
        time.time = host_time
        ctx.Join()


def main():
    engine = trusted_engine()
    requested = {int(i) for i in sys.argv[1:]}
    for trial in json.loads((ROOT / "native-jobs.json").read_bytes()):
        if trial["id"] not in requested:
            continue
        metadata = {"id": trial["id"], "coin": trial["feed"]["coin"], "start": trial["feed"]["start"], "language": "Python"}
        try:
            row = {**metadata, **replay(engine, trial)}
        except Exception as exc:
            row = {**metadata, "reason": str(exc)[:450]}
        with (ROOT / "native-trials-python.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
