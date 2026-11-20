"""Run an archived FMZ Python ticker strategy against a pinned offline tape."""

import ast
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).absolute().parent
JOB = ROOT / "r19-native-698-ticker-job.json.gz"
OUT = ROOT / "r19-native-698-ticker-receipt.json"
BALANCE = 10000


class EndOfTape(BaseException):
    pass


class OrderIntent(BaseException):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def run_case(code, settings, start_ms, poll_ms, prices, allow_first_order=False):
    count = Counter()
    state = {"clock": start_ms, "next": 0}
    controls = {}
    orders = []
    directions = []
    account = {"Balance": BALANCE, "FrozenBalance": 0, "Stocks": 0, "FrozenStocks": 0}

    def read_ticker():
        i = state["next"]
        count["ticker"] += 1
        return SimpleNamespace(Last=prices[i] / 100)

    def read_account():
        count["account"] += 1
        return SimpleNamespace(**account)

    def read_position():
        count["position"] += 1
        return []

    def read_orders():
        count["orders"] += 1
        return []

    def order(side, price, amount, *args):
        orders.append({"side": side, "limit": price, "amount": amount, "time_ms": state["clock"]})
        if allow_first_order:
            raise OrderIntent
        raise AssertionError("The complete market bound predicted no order")

    def sleep(ms):
        assert ms == poll_ms
        count["sleep"] += 1
        state["next"] += 1
        state["clock"] += ms
        if state["next"] == len(prices):
            raise EndOfTape

    def d():
        return state["clock"]

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        assert name == "time"
        return SimpleNamespace(time=lambda: state["clock"] / 1000)

    def precision(price, amount):
        controls["precision"] = [price,amount]

    exchange = SimpleNamespace(
        GetTicker=read_ticker, GetAccount=read_account, GetPosition=read_position,
        GetOrders=read_orders, GetName=lambda: "Futures_Binance",
        SetContractType=lambda typ: controls.update(contract_type=typ),
        SetMarginLevel=lambda lev: controls.update(leverage=lev),
        SetPrecision=precision, SetDirection=directions.append,
        Buy=lambda *args: order("buy", *args),
        Sell=lambda *args: order("sell", *args),
    )
    scope = {
        **settings,
        "false": False,
        "exchange": exchange,
        "_C": lambda f: f(),
        "_D": d,
        "_N": round,
        "Sleep": sleep,
        "IsVirtual": lambda: True,
        "LogStatus": lambda *args: None,
        "LogProfit": lambda *args: None,
        "__builtins__": {"__import__": importer, "len": len, "range": range, "float": float},
    }
    # This worker runs only in the pre-existing, network-denied AppContainer.
    exec(code, scope)  # noqa: S102
    try:
        scope["main"]()
    except EndOfTape:
        ending = "complete"
    except OrderIntent:
        ending = "bounded synthetic branch control"
    else:
        raise AssertionError("Main loop unexpectedly returned")
    return {
        "ending":ending, "clock_ms":state["clock"], "calls":dict(count),
        "base_price":scope["basePrice"], "directions":directions, "intents":orders,
        "ending_cash":account["Balance"], "ending_asset":account["Stocks"], "setup":controls,
    }


def main():
    raw = JOB.read_bytes()
    data = json.loads(gzip.decompress(raw))
    source = data["source"]
    assert digest(source.encode()) == data["source_sha256"] == data["author"]["archive_source_sha256"]
    tree = ast.parse(source)
    assert [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] == ["time"]
    assert not any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree))
    code = compile(tree, "pinned-fmz-698.py", "exec")
    settings = data["author"]["args"]
    assert settings == {"leverage": 1, "StopGain": 0.05, "StopLoss": 0.05}
    job = data["inputs"]
    prices = job["prices_cents"]
    start, end, interval = (job[k] for k in ("start_ms","end_ms","poll_ms"))
    seed = prices[0]
    low, high = (data["evidence"][k] for k in ("official_low_cents","official_high_cents"))
    assert low * 100 > seed * 95 and high * 100 < seed * 105
    assert low <= min(prices) <= seed <= max(prices) <= high
    output = run_case(code, settings, start, interval, prices)
    assert output["setup"] == {"precision":[2,3],"contract_type":"swap","leverage":1}
    assert output["ending"] == "complete" and output["base_price"] == seed / 100
    assert output["clock_ms"] == end == start + len(prices) * interval
    assert output["calls"] == {"ticker":len(prices),"sleep":len(prices),"account":1,"position":2}
    assert output["ending_cash"] == BALANCE and output["ending_asset"] == 0
    assert not output["directions"] and not output["intents"]

    controls = [
        run_case(code,settings,start,interval,control,allow_first_order=True)
        for control in ([10000,10500],[10000,10501],[10000,9500],[10000,9499])
    ]
    assert [row["directions"] for row in controls] == [[],["buy"],[],["sell"]]
    assert [row["ending"] for row in controls] == ["complete","bounded synthetic branch control"]*2
    receipt = {
        "job_sha256":digest(raw), "worker_sha256":digest(Path(__file__).read_bytes()),
        "source_sha256":data["source_sha256"], "source_settings":settings,
        "observed_prices": {"first_cents":seed,"min_cents":min(prices),"max_cents":max(prices)},
        "observed_run":output,
        "exact_bound_controls":controls,
        "assumptions": {
            "flat_start_cash_USDT":BALANCE,
            "virtual_fmz_host_compatibility":"Expose the lowercase false alias as the Python boolean False. The branch for a nonvirtual instance stays inactive. No source line was rewritten.",
            "clock":"Recorded event-availability time is compared to a 500 ms virtual poll timer. The initial poll is one minute into the first complete UTC day to seed last trade causally."
        }
    }
    OUT.write_text(json.dumps(receipt,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
