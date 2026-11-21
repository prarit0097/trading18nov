"""Settle #3038 under FMZ's documented pending-entry bracket policy."""

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    ledger_metrics,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round34_3038 import (
    DAY,
    FEE,
    SOURCE,
    directed_prices,
    min_candles,
    next_touch,
    trade_tape,
)

PRIOR = "0fd2f2fb133c375610a75988893684045767f40d2f5bb009c8d1664ea9ed38c0"
STARTING_EQUITY = Decimal(100)
LOT = Decimal(".001")


def settle_case(item, prior, rates, end, minute_source, daily, receipts, tapes):
    market = item["market"]
    assert prior["market"] == market
    chart = item["chart"]
    assert len(chart) == 371 and chart[-1][0] == end - DAY
    [path] = verified_archives(minute_source, market, "1m", ("2023-11",), receipts)
    minutes = min_candles(path, end - 7 * DAY, end)
    assert [list(row[:5]) for row in aggregate(minutes, 1440)] == [
        r[:5] for r in chart[-7:]
    ]

    def subminute(bar):
        day = datetime.fromtimestamp(bar[0] / 1000, UTC).strftime("%Y-%m-%d")
        return trade_tape(daily, market, day, [bar], tapes)[bar[0]]

    attempted, trades = [], []
    tick = Decimal(".10" if market == "BTCUSDT" else ".01")
    for i in range(365, 371):
        signal, decision_price = chart[i - 1][0], chart[i - 1][4]
        day = chart[i][0]
        offset = (i - 364) * 1440
        limit, stop, target = directed_prices(decision_price, tick)
        children = minutes[offset : offset + 1440]
        entry, exit_fill = next_touch(children, limit, stop, target, subminute)
        attempted.append(
            {
                "submitted_at": day,
                "limit": limit,
                "stop": stop,
                "target": target,
                "matched": entry is not None,
            }
        )
        if entry is None:
            continue
        assert i == 365 and exit_fill and exit_fill[3] == "target"
        assert entry[0] < exit_fill[0] < day + DAY
        assert entry[1] == prior["prepared_grid_levels"]["limit"]
        assert exit_fill[1] == prior["prepared_grid_levels"]["target"]
        assert (
            entry[0] == prior["grid_open"][0]
            and exit_fill[0] == prior["first_minute_bracket_touch"][0]
        )
        assert entry[2][3] <= limit - float(tick) and exit_fill[2][2] >= target + float(
            tick
        )
        # A quoted touch is an execution opportunity. Where raw prints cross both same-minute
        # levels, next_touch explicitly waits for entry and uses the observed trade sequence.
        open_usd = Decimal(str(entry[1])) * rates[day]
        exit_usd = Decimal(str(exit_fill[1])) * rates[day]
        signal_usd = Decimal(str(decision_price)) * rates[signal]
        quantities = {
            "signal-close sizing": STARTING_EQUITY
            / (signal_usd * (1 + FEE))
            // LOT
            * LOT,
            "fill-price sizing": STARTING_EQUITY / (open_usd * (1 + FEE)) // LOT * LOT,
        }
        assert (
            float(quantities["signal-close sizing"])
            == prior["signal_close_native_quantity"]
        )
        assert (
            float(quantities["fill-price sizing"])
            == prior["price_basis_piner_quantity"]
        )
        for sizing, quantity in quantities.items():
            assert 0 < open_usd * quantity * (1 + FEE) <= STARTING_EQUITY
            cost = (open_usd + exit_usd) * quantity * FEE
            gross = (exit_usd - open_usd) * quantity
            trade = {
                "entryTime": entry[0],
                "exitTime": exit_fill[0],
                "qty": float(quantity),
                "dir": 1,
                "entryPrice": float(open_usd),
                "exitPrice": float(exit_usd),
                "commission": float(cost),
                "profit": float(gross - cost),
                "sizing": sizing,
            }
            trades.append(trade)
    # The last allowed candle closes at the archived endpoint, with no later tradable bar.
    assert len(trades) == 2 and sum(x["matched"] for x in attempted) == 1
    final_limit, final_stop, final_target = directed_prices(chart[-1][4], tick)
    return {
        "market": market,
        "minute_count": len(minutes),
        "settled": trades,
        "six_executable_candle_plans": attempted,
        "at_cutoff_entry_limit": final_limit,
        "at_cutoff_stop": final_stop,
        "at_cutoff_target": final_target,
        "alternative_daily_close_exit": prior["original_grid_unbound_exit"]["price"],
        "prior_receipt_entry": prior["grid_open"],
        "prior_receipt_exit": prior["first_minute_bracket_touch"],
    }


def main(document, stage, prior_path, minute_source, daily, output):
    assert sha256(document) == SOURCE and sha256(prior_path) == PRIOR
    audit = read(prior_path)
    assert sha256(stage) == audit["input_sha256"]
    data = read(stage)
    end = data["end"]
    assert end == audit["replay_clock"]
    rows = data["fx"]["pairs"][0]["rates"]
    rates = {r["effectiveTime"]: Decimal(str(r["rate"])) for r in rows}
    tapes, receipts = {}, []
    cases = [
        settle_case(item, prior, rates, end, minute_source, daily, receipts, tapes)
        for item, prior in zip(data["cases"], audit["cases"], strict=True)
    ]
    assert (
        receipts == audit["minute_receipts"]
        and list(tapes.values()) == audit["trade_tape_receipts"]
    )
    results = []
    for sizing in ("signal-close sizing", "fill-price sizing"):
        common = {
            "id": 3038,
            "group": "FMZ pre-entry bracket · " + sizing,
            "period": "2022-11-21 to 2023-11-27 UTC exclusive",
            "currency": "USD",
            "interval": "1d with 1m and trade chronology",
            "archive_interval": "1d",
            "pine_source_version": "4",
            "order_family": "Entry limit with waiting one-cancels-other bracket",
            "exit": "First reachable source target or stop after entry",
        }
        for selected in ([cases[0]], [cases[1]], cases):
            closed = [
                t for c in selected for t in c["settled"] if t["sizing"] == sizing
            ]
            results.append(
                {
                    **common,
                    "market": " + ".join(c["market"] for c in selected),
                    **ledger_metrics(closed, float(STARTING_EQUITY) * len(selected), 0),
                }
            )
    write(
        output,
        {
            "schema": "FMZ #3038 documented pre-entry bracket with recorded minute and trade chronology",
            "source_sha256": SOURCE,
            "source_url": audit["source_url"],
            "prior_evidence_sha256": PRIOR,
            "input_sha256": sha256(stage),
            "data_archives": receipts,
            "raw_witness": list(tapes.values()),
            "reference": "https://www.fmz.com/doc/9293#strategy.exit",
            "cases": cases,
            "results": results,
            "notes": "The authored clock uses the archived endpoint. Per FMZ documentation an exit waits for the outstanding entry, then it is placed. This model puts the authored INSTANT bracket live at entry and cancels its other side after a fill. Order prices round toward the exchange grid without weakening the source limit protections. For the ETH entry minute raw trades establish that the intraminute high preceding entry cannot trigger the target. Each market is flat before the next daily decision, so the later price-less or position-aware exits never control this model. The replay measures observed price opportunities and leaves actual FMZ fills and queue placement unresolved. The archived native daily controls remain in the prior evidence. Two observed engine sizing bases are stated separately using the source fee and prior-day USD conversion. No funding time falls between the model's entry and exit.",
            "coverage": [
                [
                    3038,
                    "Tested · documented waiting-bracket chronology and two sizing bases",
                    "A source-documented pending-entry bracket settles on independently verified observed BTC and ETH price paths. Raw ETH sequence resolves its first ambiguous minute. Signal-close and fill-price sizing remain distinct; host parity is unverified.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
