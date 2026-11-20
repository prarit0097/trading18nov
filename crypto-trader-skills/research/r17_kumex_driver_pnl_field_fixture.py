"""Run archived #4383 in the network-denied runner against pinned inverse tapes."""

import hashlib
import io
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, getcontext
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).absolute().parent
JOB = ROOT / "r17-kumex-driver-jobs.json"
RECEIPT = ROOT / "r17-kumex-driver-pnl-field-receipt.json"
getcontext().prec = 40
ZERO = Decimal(0)


class TestWindowEnd(BaseException):
    pass


class OfflineTrade:
    def __init__(self, tape):
        self.spec = tape["spec"]
        self.symbol = tape["symbol"]
        self.inputs = tape["inputs"]
        self.index = 0
        self.qty = 0
        self.basis = ZERO
        self.fee = Decimal(str(self.spec["takerFeeRate"]))
        self.maintenance = Decimal(str(self.spec["maintainMargin"]))
        assert self.spec["isInverse"] and self.spec["multiplier"] == -1
        self.leverage = Decimal(20)
        self.cash = Decimal(10000) / self.mark()
        self.opening_cash = self.cash
        self.events = []
        self.max_positions = 0
        self.risk_margin = Decimal(999)
        self.exposure_expenses = ZERO

    def mark(self):
        # The tape records the most recent complete mark candle.
        return Decimal(self.inputs[self.index][10])

    def pnl(self, mark):
        if self.qty == 0:
            return ZERO
        side = 1 if self.qty > 0 else -1
        return side * (self.basis - abs(self.qty) / mark)

    def risk_check(self, mark):
        if self.qty:
            initial = self.basis / self.leverage
            requirement = abs(self.qty) / mark * (self.maintenance + self.fee)
            available = initial + self.pnl(mark) - self.exposure_expenses
            self.risk_margin = min(self.risk_margin, available - requirement)
            if available <= requirement:
                raise ValueError(
                    "Potential isolated-margin liquidation within a mark bar"
                )

    def sleep(self, t):
        assert t == 60
        self.index += 1
        row = self.inputs[self.index]
        self.risk_check(Decimal(row[8] if self.qty < 0 else row[9]))
        rate = row[-1]
        if rate is not None:
            settled = -Decimal(str(rate)) * self.qty / self.mark()
            self.cash += settled
            self.exposure_expenses += max(-settled, ZERO)
            self.events.append(
                {
                    "kind": "funding",
                    "time": row[0],
                    "mark": str(self.mark()),
                    "rate": str(rate),
                    "qty": self.qty,
                    "settled": str(settled),
                }
            )
        if self.index == len(self.inputs) - 1:
            raise TestWindowEnd()

    def get_position_details(self, symbol):
        assert symbol == self.symbol
        pct = self.pnl(self.mark()) / self.basis if self.qty else ZERO
        shown = pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        return {"unrealisedPnlPcnt": str(shown)}

    def create_market_order(self, symbol, side, leverage, *, type, size):
        assert symbol == self.symbol and side in ("buy", "sell") and size in (1, 2)
        assert Decimal(leverage) == self.leverage and type == "market"
        row = self.inputs[self.index]
        moment, receive, exchange, bid, ask, bid_size, ask_size = row[:7]
        assert receive <= moment * 1_000_000 and exchange <= moment * 1_000_000
        assert Decimal(bid) <= Decimal(ask)
        price, visible = (ask, ask_size) if side == "buy" else (bid, bid_size)
        price = Decimal(price)
        assert Decimal(visible) >= size and price > 0
        delta = size if side == "buy" else -size
        fee = Decimal(size) / price * self.fee
        realized = ZERO
        closing = 0
        if self.qty * delta < 0:
            closing = min(abs(self.qty), size)
            closed_basis = self.basis * closing / abs(self.qty)
            sign = 1 if self.qty > 0 else -1
            realized = sign * (closed_basis - closing / price)
            self.basis -= closed_basis
            self.qty -= closing * sign
            if not self.qty:
                self.exposure_expenses = ZERO
        expanding = size - closing
        if expanding:
            self.basis += Decimal(expanding) / price
            self.qty += expanding if delta > 0 else -expanding
        self.cash += realized - fee
        self.exposure_expenses += fee
        assert self.cash > self.basis / self.leverage + fee
        self.risk_check(self.mark())
        self.max_positions = max(self.max_positions, abs(self.qty))
        self.events.append(
            {
                "kind": "market",
                "time": moment,
                "mark": str(self.mark()),
                "book_price": str(price),
                "book_visible": visible,
                "quote_received_us": receive,
                "side": side,
                "size": size,
                "closing": closing,
                "fee": str(fee),
                "realized": str(realized),
                "qty": self.qty,
                "basis": str(self.basis),
                "cash": str(self.cash),
            }
        )
        return {"orderId": len(self.events)}


def run(trial, source):
    broker = OfflineTrade(trial)
    allowed_modules = {
        "json": json,
        "time": SimpleNamespace(sleep=broker.sleep),
        "kumex.client": SimpleNamespace(Trade=lambda *args, **kwargs: broker),
    }
    config = {
        "api_key": "",
        "api_secret": "",
        "api_passphrase": "",
        "is_sandbox": True,
        "symbol": trial["symbol"],
        "timer": 1,
        "size": 1,
        "side": "sell",
        "leverage": "20",
        "rate": 0.03,
    }

    def imports(name, globals=None, locals=None, fromlist=(), level=0):
        return allowed_modules[name]

    def open_fixture(name, mode):
        assert name == "config.json" and mode == "r"
        return io.StringIO(json.dumps(config))

    namespace = {
        "__name__": "__main__",
        "__builtins__": {
            "__build_class__": __build_class__,
            "__import__": imports,
            "object": object,
            "int": int,
            "float": float,
            "abs": abs,
            "open": open_fixture,
            "print": lambda *args: None,
        },
    }
    try:
        # The caller runs the AST-reviewed pinned source in a network-denied AppContainer.
        exec(compile(source, "pinned-fmz-4383", "exec"), namespace)  # noqa: S102
    except TestWindowEnd:
        return {
            "symbol": broker.symbol,
            "day": trial["day"],
            "minutes": broker.index,
            "events": broker.events,
            "ending_contracts": broker.qty,
            "ending_basis": str(broker.basis),
            "ending_wallet": str(broker.cash),
            "starting_wallet": str(broker.opening_cash),
            "ending_mark": str(broker.mark()),
            "ending_unrealized": str(broker.pnl(broker.mark())),
            "largest_position": broker.max_positions,
            "min_isolated_margin_excess": str(broker.risk_margin),
        }
    raise ValueError("Source returned before the replay cutoff")


if __name__ == "__main__":
    raw = JOB.read_bytes()
    data = json.loads(raw)
    assert hashlib.sha256(data["source"].encode()).hexdigest() == data["source_sha256"]
    results = []
    for trial in data["tapes"]:
        try:
            results.append(run(trial, data["source"]))
        except (
            AssertionError,
            IndexError,
            InvalidOperation,
            KeyError,
            NameError,
            ValueError,
        ) as exc:
            results.append(
                {
                    "symbol": trial["symbol"],
                    "day": trial["day"],
                    "reason": str(exc) or type(exc).__name__,
                }
            )
    out = {
        "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "job_sha256": hashlib.sha256(raw).hexdigest(),
        "results": results,
    }
    RECEIPT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
