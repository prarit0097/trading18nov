"""Replay the published DCA settings for #4681 on recorded Binance Spot quotes."""

import ast
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from research.fmz_round7_magnifier import date_ms, ledger_metrics, sha256, write

SOURCE_SHA = "f62aa7392d9cb32a0c0c4cebd7d9e920b0346bd3560e860e8441ab9b92830e4c"
CODE_SHA = "99c33bf7798879bd9741ec7fd06ff09d7eee62b0222ec3d8ad5a9dd40395dfa7"
PUBLISHER = "https://www.fmz.com/strategy/54256"
DATES = ("2021-05-01", "2021-06-01")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SECOND = 1_000_000
CAPITAL = 10_000
CEILING_LOG = "Bid Price >= maxBidPrice, not process"


class ReplayCutoff(Exception):
    """The next 60-second poll lands outside the historical window."""


def read_strategy(document, settings_report):
    assert sha256(document) == SOURCE_SHA
    previous = json.loads(settings_report.read_bytes())
    (matched,) = [p for p in previous["evidence"] if p["id"] == 4681]
    assert matched["document_sha256"] == SOURCE_SHA
    assert matched["code_sha256"] == CODE_SHA
    assert matched["publisher_page"] == PUBLISHER
    settings = matched["public_settings"]["args"]
    assert settings == {
        "orderAmount": 1,
        "maxBidPrice": 0,
        "accountLimitMoney": 0,
        "orderTimeInterval": 60,
    }
    fence = chr(96) * 3
    (source,) = re.findall(
        r"(?ms)^" + fence + r" python[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    import hashlib

    assert hashlib.sha256(source.encode()).hexdigest() == CODE_SHA
    parsed = ast.parse(source)
    calls = [node for node in ast.walk(parsed) if isinstance(node, ast.Call)]
    observed = Counter(
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in calls
    )
    assert observed == {
        "len": 1,
        "range": 1,
        "GetAccount": 1,
        "GetName": 1,
        "GetDepth": 1,
        "GetCurrency": 1,
        "Log": 4,
        "Buy": 1,
        "onTick": 1,
        "sleep": 1,
    }
    (buy,) = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "Buy"
    ]
    assert len(buy.args) == 1 and ast.unparse(buy.args[0]) == "amount"
    checks = [node for node in ast.walk(parsed) if isinstance(node, ast.If)]
    assert any(ast.unparse(x.test) == "bidPrice < maxBidPrice" for x in checks)
    return compile(parsed, "FMZ #4681", "exec"), settings, matched["public_settings"]


def snapshot_grid(path, symbol, polls):
    start, end = polls[0], polls[-1] + 60 * SECOND
    samples = {}
    n_rows = 0
    close = None
    grid = iter(polls)
    next_poll = next(grid)
    last_timestamp = 0
    last = None
    with gzip.open(path, "rt", encoding="ascii", newline="") as stream:
        assert stream.readline().rstrip().split(",") == [
            "exchange",
            "symbol",
            "timestamp",
            "local_timestamp",
            "ask_amount",
            "ask_price",
            "bid_price",
            "bid_amount",
        ]
        for line in stream:
            exchange, market, published, captured, ask_size, ask, bid, bid_size = (
                line.rstrip().split(",")
            )
            t = int(captured)
            if t > end:
                close = t
                break
            assert exchange == "binance" and market == symbol and t >= last_timestamp
            last_timestamp = t
            if start - 5 * SECOND <= t < end:
                n_rows += 1
            while next_poll is not None and t > next_poll:
                assert last is not None
                samples[next_poll] = last
                next_poll = next(grid, None)
            if next_poll is None:
                close = t
                break
            last = (
                t,
                int(published),
                float(ask),
                float(ask_size),
                float(bid),
                float(bid_size),
            )
    assert close is not None and tuple(samples) == polls
    for poll, (capture, venue_time, ask, ask_size, bid, bid_size) in samples.items():
        assert 0 <= poll - capture <= 5 * SECOND
        assert venue_time > 0 and 0 < bid < ask and ask_size > 0 and bid_size > 0
    return samples, n_rows


class RecordedTopOfBook:
    def __init__(self, symbol, quotes, clock):
        self.symbol = symbol
        self.quotes = quotes
        self.clock = clock
        self.checked = {}
        self.wallet = {"Balance": CAPITAL, "Stocks": 0}

    def GetAccount(self):
        return self.wallet.copy()

    def GetName(self):
        return "Binance"

    def GetCurrency(self):
        return self.symbol

    def GetDepth(self):
        stamp = self.clock.poll
        assert stamp not in self.checked
        captured, venue_time, ask, ask_size, bid, bid_size = self.quotes[stamp]
        self.checked[stamp] = (captured, venue_time, ask)
        return {
            "Asks": [{"Price": ask, "Amount": ask_size}],
            "Bids": [{"Price": bid, "Amount": bid_size}],
        }

    def Buy(self, amount):
        raise AssertionError(
            f"Unexpected authored buy branch at {self.clock.poll} for {amount!r}"
        )


def execute(code, settings, polls, feeds):
    clock = SimpleNamespace(poll=polls[0])
    venues = [RecordedTopOfBook(market, feed, clock) for market, feed in feeds.items()]
    log = Counter()

    def sleep(delay):
        assert delay == settings["orderTimeInterval"] == 60
        assert all(clock.poll in market.checked for market in venues)
        clock.poll += delay * SECOND
        if clock.poll == polls[-1] + delay * SECOND:
            raise ReplayCutoff

    def observe(*args):
        if args == (CEILING_LOG,):
            log["ceiling"] += 1
        else:
            assert args[0] == "Market ", args
            log["wallet_and_market"] += 1

    host = {
        "__builtins__": {"len": len, "range": range},
        "time": SimpleNamespace(sleep=sleep),
        "Log": observe,
        "exchanges": venues,
        **settings,
    }
    # The complete source and executable text are independently hash-pinned above.
    exec(code, host)  # noqa: S102
    try:
        host["main"]()
    except ReplayCutoff:
        pass
    else:
        raise AssertionError("The source did not reach the expected cutoff")
    assert log == {
        "ceiling": len(polls) * len(venues),
        "wallet_and_market": len(polls) * len(venues),
    }
    for venue in venues:
        assert tuple(venue.checked) == polls and venue.wallet == {
            "Balance": CAPITAL,
            "Stocks": 0,
        }
        for stamp, reg in venue.checked.items():
            assert reg == venue.quotes[stamp][:3]
    return dict(log)


def main(document, quote_directory, settings_report, output):
    code, settings, source_proof = read_strategy(document, settings_report)
    archive_inputs, results, cases = [], [], []
    for day in DATES:
        midnight = date_ms(day) * 1000
        start, end = (midnight + hour * 3600 * SECOND for hour in (6, 10))
        polls = tuple(range(start, end, 60 * SECOND))
        feeds = {}
        for market in SYMBOLS:
            path = quote_directory / f"{market}-{day}.csv.gz"
            feeds[market], captured = snapshot_grid(path, market, polls)
            year, month, number = day.split("-")
            archive_inputs.append(
                {
                    "symbol": market,
                    "day": day,
                    "sha256": sha256(path),
                    "url": f"https://datasets.tardis.dev/v1/binance/quotes/{year}/{month}/{number}/{market}.csv.gz",
                }
            )
            samples = feeds[market]
            cases.append(
                {
                    "symbol": market,
                    "day": day,
                    "quotes_examined_through_last_poll": captured,
                    "polls": len(polls),
                    "lowest_ask": min(v[2] for v in samples.values()),
                    "longest_quote_age_ms": max(
                        (poll - v[0]) / 1000 for poll, v in samples.items()
                    ),
                    "reachable_buy_predicates": sum(
                        v[2] < settings["maxBidPrice"] for v in samples.values()
                    ),
                }
            )
            assert all(v[2] > settings["maxBidPrice"] for v in samples.values())
        assert execute(code, settings, polls, feeds)["ceiling"] == len(polls) * 2
        common = {
            "id": 4681,
            "group": "FMZ Python · Archived DCA price ceiling",
            "period": f"{day} 06:00–10:00 UTC",
            "exit": "No exit rule in source",
            "interval": "60s",
            "currency": "USDT",
            "archive_interval": "60s polling",
            "order_family": "Buy below configured maximum",
        }
        for market, capital in (
            *((m, CAPITAL) for m in SYMBOLS),
            ("BTCUSDT + ETHUSDT", 2 * CAPITAL),
        ):
            results.append(
                {**common, "market": market, **ledger_metrics([], capital, 0)}
            )
    write(
        output,
        {
            "schema": "FMZ #4681 original default spot DCA replay",
            "source_sha256": SOURCE_SHA,
            "python_program_sha256": CODE_SHA,
            "origin": PUBLISHER,
            "settings_evidence": source_proof,
            "archive_inputs": archive_inputs,
            "preservation": "The archived Python loop runs unchanged. The history adapter exposes recorded best bids and asks, isolated wallets and the authored 60-second sleep. All four underlying streams are explicit BTC and ETH generic spot benchmark bindings, because the original strategy does not bind a default venue or symbol.",
            "limits": "Published maxBidPrice=0 rejects every valid positive ask before the one-argument buy API is reached. Four instrument scopes finish with no fills, inventory, fees or realized drawdown. These results measure the published default and do not exercise a nonzero threshold, order admission or settlement.",
            "references": [
                "https://docs.tardis.dev/historical-data-details/binance",
                "https://docs.tardis.dev/downloadable-csv-files/data-types",
            ],
            "coverage": [
                [
                    4681,
                    "Tested · published DCA default blocks all spot buys",
                    "Executed the unchanged 60s source on four recorded Binance BTC/ETH Spot scopes using the publisher-matched zero ceiling. Independently verified 960 eligible-to-check positive asks and zero buy calls.",
                ]
            ],
            "cases": cases,
            "results": results,
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
