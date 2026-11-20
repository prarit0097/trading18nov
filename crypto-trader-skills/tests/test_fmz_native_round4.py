import hashlib
import json
from math import isclose

from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, stamp
from research.fmz_native_expanded_replay import order_metrics
from research.fmz_native_round4 import trace_error


def test_native_python_market_buy_fees_are_charged_on_filled_turnover(tmp_path):
    start, end = "2026-09-23", "2026-10-21"
    begin, terminal = stamp(start) * 1000, stamp(end) * 1000
    tape = json.dumps({"data": [[begin, 100, 100, 100, 100, 1], [begin + 60_000, 110, 110, 110, 110, 1]]}).encode()
    (tmp_path / "market.json").write_bytes(tape)
    feed = dict(start=start, end=end, file="market.json", sha256=hashlib.sha256(tape).hexdigest(),
                base_seconds=60, symbol="BTC_USDT")
    buy, sell = (
        dict(Id=1, Time=begin, DealAmount=10, AvgPrice=100, Price=0, Type=0, Symbol="BTC_USDT"),
        dict(Id=2, Time=begin + 60_000, DealAmount=10, AvgPrice=110, Price=0, Type=1, Symbol="BTC_USDT"),
    )

    def account(balance, stocks):
        return dict(Balance=balance, Stocks=stocks, FrozenBalance=0, FrozenStocks=0)

    cash = EQUITY - 1000 * (1 + FEE)
    ending = cash + 1100 * (1 - FEE)
    record = dict(orders=[buy, sell], account=account(ending, 0), last={"Time": terminal - 10_000},
                  trade_account={"1": (account(EQUITY, 0), account(cash, 10)),
                                 "2": (account(cash, 10), account(ending, 0))})
    [lot], opened, checked = order_metrics(
        record, {"feed": feed, "directory": tmp_path}, market_buy_fee_on_turnover=True,
    )
    assert opened == 0 and abs(checked["cash_error"]) < 1e-9
    assert trace_error(record) < 1e-9
    assert isclose(lot[1], 100)
    assert isclose(lot[2], 100 - 2100 * FEE)
    assert isclose(lot[3], 100 - 2100 * (FEE + EXECUTION))
