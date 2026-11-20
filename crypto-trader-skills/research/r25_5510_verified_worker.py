"""Run the pinned FMZ ticker breakout against the Binance spot size guard."""

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


ROOT=Path(__file__).absolute().parent
JOB=ROOT/"r25-5510-source-tape.json.gz"
OUT=ROOT/"r25-5510-native-receipt.json"
BALANCES=(10_000,100_000)


class EndOfWindow(BaseException):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run(code, tape, options, minimum, cash):
    prices=[float(v) for v in tape["price"]]
    counts=Counter()
    index=0
    intents=[]
    clock=tape["begin_ms"]
    account=SimpleNamespace(Balance=cash,Stocks=0,FrozenBalance=0,FrozenStocks=0)
    assert 0 < min(prices) <= max(prices) < 2*min(prices)

    def ticker():
        counts["ticker"]+=1
        return SimpleNamespace(Last=prices[index])

    def balance():
        counts["account"]+=1
        return account

    def sleep(ms):
        nonlocal index,clock
        assert ms==60000
        index+=1
        clock+=ms
        if index==len(prices):
            raise EndOfWindow

    def buy(price,amount):
        assert price==-1 and amount==1 and amount<=cash
        assert float(tape["max_notional_bound"])*amount < minimum
        counts["rejected_buy"]+=1
        intents.append({"time":clock, "last":prices[index],"quote_order_qty":amount,
                        "error":"Binance model NOTIONAL size guard rejects the quote amount"})
        return None

    def sell(*args):
        raise AssertionError("Position-free source should never enter its Sell branch")

    def log(message):
        if message.startswith("buy "):counts["buy_signal"]+=1
        if message.startswith("sell "):counts["sell_signal"]+=1
        if message.startswith("buy id"):counts["buy_signal"]-=1

    env={
        **options,"true":True,
        "exchange":SimpleNamespace(GetTicker=ticker,GetAccount=balance, Buy=buy,Sell=sell),
        "Sleep":sleep,"Log":log,
        "__builtins__":{"len":len,"max":max,"min":min,"str":str},
    }
    # Only the hash-checked source block runs in the AppContainer.
    exec(code,env)  # noqa: S102
    try:
        env["main"]()
    except EndOfWindow:
        pass
    else:
        raise AssertionError("Original source unexpectedly stopped before boundary")
    assert clock==tape["end_ms"] and counts["ticker"]==len(prices)
    assert account.Balance==cash and account.Stocks==0 and account.FrozenBalance==account.FrozenStocks==0
    assert len(env["list"])==options["LENGTH"]
    return {"coin":tape["coin"],"begin_ist":tape["begin_ist"],"end_ist":tape["end_ist"],
            "balance":cash,"counts":dict(counts),"boundary_ms":clock,"rejects":intents,
            "ending_cash":account.Balance,"ending_stock":account.Stocks,"frozen_quote":account.FrozenBalance,
            "fills":0,"fees_collected":0}


def main():
    raw=JOB.read_bytes()
    job=json.loads(gzip.decompress(raw))
    assert sha(job["code"].encode())==job["code_sha256"]=="be44e1fc60b138cd1ae07a4150361e1692685852e8860470a76f13cac3a378ab"
    assert job["args"]=={"PERIOD":60,"LENGTH":1440}
    code=compile(job["code"],"archived-fmz-5510.py","exec")
    filters,alt=job["filter_receipts"]
    assert filters["filter"]==alt["filter"]
    trials=[]
    for t in job["scopes"]:
        condition=filters["filter"][t["coin"]+"USDT"]
        assert condition["markets_allowed"] and condition["apply_min_to_market"]
        for size in BALANCES:
            trials.append(run(code,t,job["args"],float(condition["min_notional"]),size))
    receipt={"job_sha256":sha(raw),"worker_sha256":sha(Path(__file__).read_bytes()),
             "source_sha256":job["code_sha256"],"trials":trials}
    with OUT.open("x",encoding="utf-8",newline="\n") as file:
        file.write(json.dumps(receipt,separators=(",",":"),ensure_ascii=False)+"\n")


if __name__=="__main__":
    main()
