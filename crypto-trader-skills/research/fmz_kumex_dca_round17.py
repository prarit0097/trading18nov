"""Stage the pinned KuMEX DCA driver and reconcile its inverse historical ledger."""

import argparse
import ast
import json
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, drawdown, summarize
from research.fmz_native_expanded_replay import BLOCKS
from research.fmz_native_round6_audit import ROOT, digest

IDENT = 4383
PUBLISHER = "https://www.fmz.com/strategy/207710"
JOB = "r17-kumex-driver-jobs.json"
RECEIPT = "r17-kumex-driver-pnl-field-receipt.json"
FIXTURE = "r17_kumex_driver_pnl_field_fixture.py"
MINUTES = 480
ZERO = Decimal(0)
EPS = Decimal("1e-34")
LOT_PRECISION = Decimal("0.00000001")


def check(approx, logged):
    assert abs(approx - Decimal(logged)) < EPS


def stage(archive, compact, target):
    item = next(
        x
        for x in read(ROOT / "remaining-backtest-round15-coverage.json")["disposition"]
        if x["id"] == IDENT
    )
    with ZipFile(archive) as zip_source:
        pathname = unquote(item["source"].rsplit("/", 1)[-1])
        content = zip_source.read(f"strategies-{FMZ_REF}/{pathname}")
    full = content.decode()
    assert PUBLISHER in full
    assert (
        "每分钟定投1手空单，20倍杠杆" in full
        and "如果盈利超过3%，每分钟平仓2手" in full
    )
    [source] = [
        part.lstrip("\r\n")
        for tag, part in BLOCKS.findall(full)
        if tag.strip() == "python"
    ]
    tree = ast.parse(source)
    imports = {
        a.name for x in ast.walk(tree) if isinstance(x, ast.Import) for a in x.names
    }
    imports.update(x.module for x in ast.walk(tree) if isinstance(x, ast.ImportFrom))
    assert imports == {"json", "time", "kumex.client"}
    assert source.count("Trade(") == source.count("get_position_details(") == 1
    raw_tape = compact.read_bytes()
    write(
        target / JOB,
        {
            "tapes": json.loads(raw_tape),
            "tape_sha256": digest(raw_tape),
            "archive": item["source"],
            "document_sha256": digest(content),
            "source": source,
            "source_sha256": digest(source.encode()),
        },
    )


def verify_ledger(case, receipt):
    tapes = case["inputs"]
    assert len(tapes) == MINUTES + 1 and receipt["minutes"] == MINUTES
    assert not receipt.get("reason")
    assert case["spec"]["lotSize"] == 1 and case["spec"]["initialMargin"] <= 0.05
    settled = Decimal(receipt["starting_wallet"])
    initial = Decimal(EQUITY) / Decimal(tapes[0][10])
    assert abs(settled - initial) < EPS
    fee_rate = Decimal(str(case["spec"]["takerFeeRate"]))
    signed_qty = 0
    open_basis = carry = position_cash = total_funding = total_fees = ZERO
    total_turnover = raw_pct_max = ZERO
    rounding_bias = ZERO
    ledger, usd_marks, ages = [], [], []
    groups = {}
    largest = 0
    for event in receipt["events"]:
        bucket = groups.setdefault(event["time"], {})
        assert event["kind"] not in bucket
        bucket[event["kind"]] = event
    for i, row in enumerate(tapes):
        t, recv, supplied, bid, ask, bid_amount, ask_amount = row[:7]
        mark = Decimal(row[10])
        assert t == case["start"] + i * 60 and recv <= t * 1_000_000
        assert supplied <= t * 1_000_000 and Decimal(0) < Decimal(bid) <= Decimal(ask)
        b = groups.pop(t, {})
        if row[-1] is not None:
            funding = b.pop("funding")
            expected = -signed_qty * Decimal(str(row[-1])) / mark
            assert funding["qty"] == signed_qty and Decimal(funding["rate"]) == Decimal(
                str(row[-1])
            )
            check(expected, funding["settled"])
            settled += expected
            carry += expected
            total_funding += expected
        trade = b.pop("market", None)
        assert not b
        prior_sign = (signed_qty > 0) - (signed_qty < 0)
        before_upnl = prior_sign * (open_basis - abs(signed_qty) / mark)
        pct = before_upnl / open_basis if open_basis else ZERO
        raw_pct_max = max(raw_pct_max, abs(pct))
        rounded_pct = float(pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        assert (float(pct) < -0.03) == (rounded_pct < -0.03)
        assert (float(pct) > 0.03) == (rounded_pct > 0.03)
        expected_order = None
        if i == 0 or (i < MINUTES and rounded_pct < -0.03):
            expected_order = ("sell", 1)
        elif i < MINUTES and rounded_pct > 0.03:
            expected_order = ("buy", 2)
        assert expected_order == ((trade["side"], trade["size"]) if trade else None)
        if trade is None:
            continue
        assert trade["mark"] == str(mark)
        side, size = expected_order
        expected_price, available = (
            (ask, ask_amount) if side == "buy" else (bid, bid_amount)
        )
        assert trade["book_price"] == expected_price and Decimal(available) == Decimal(
            trade["book_visible"]
        )
        assert Decimal(available) >= size and trade["quote_received_us"] == recv
        ages.append(t - recv / 1_000_000)
        direction = 1 if side == "buy" else -1
        price = Decimal(expected_price)
        new_qty = signed_qty + direction * size
        closing = min(abs(signed_qty), size) if direction == -prior_sign else 0
        assert closing == trade["closing"] and new_qty == trade["qty"]
        net_execution = direction * Decimal(size) / price
        total_turnover += abs(net_execution)
        old_cash = position_cash
        position_cash += net_execution
        fees = abs(net_execution) * fee_rate
        check(fees, trade["fee"])
        total_fees += fees
        rounding_bias += fees.quantize(LOT_PRECISION, rounding=ROUND_CEILING) - fees
        realized = ZERO
        if closing:
            realized_basis = open_basis * closing / abs(signed_qty)
            realized = prior_sign * (realized_basis - Decimal(closing) / price)
            matched_carry = carry * closing / abs(signed_qty)
            turnover = realized_basis + Decimal(closing) / price
            fee_only = realized - turnover * fee_rate
            slippage = turnover * Decimal(str(EXECUTION))
            entry = (
                realized,
                fee_only,
                fee_only + matched_carry - slippage,
                matched_carry,
                slippage,
            )
            ledger.append((t, *map(float, entry)))
            usd_marks.append((t, *(float(value * mark) for value in entry)))
            carry -= matched_carry
            open_basis -= realized_basis
        if size > closing:
            open_basis += Decimal(size - closing) / price
        assert abs((position_cash - old_cash) - net_execution) < EPS
        check(open_basis, trade["basis"])
        check(realized, trade["realized"])
        settled += realized - fees
        check(settled, trade["cash"])
        signed_qty = new_qty
        largest = max(largest, abs(signed_qty))
    assert not groups and largest == receipt["largest_position"]
    assert signed_qty == receipt["ending_contracts"]
    check(open_basis, receipt["ending_basis"])
    check(settled, receipt["ending_wallet"])
    end_mark = Decimal(tapes[-1][10])
    check(end_mark, receipt["ending_mark"])
    terminal_equity = (
        initial + position_cash - signed_qty / end_mark - total_fees + total_funding
    )
    observed_open = Decimal(receipt["ending_unrealized"])
    check(terminal_equity, settled + observed_open)
    assert Decimal(receipt["min_isolated_margin_excess"]) > 0
    evidence = {
        "ending_open_contracts": signed_qty,
        "executed_market_orders": len(ages),
        "largest_position_contracts": largest,
        "closed_lots_events": len(ledger),
        "fee_coin": str(total_fees),
        "funding_coin": str(total_funding),
        "max_abs_input_pnl_percent": str(raw_pct_max * 100),
        "hypothetical_fee_8dp_total_extra_coin": str(rounding_bias),
        "min_isolated_margin_excess_coin": receipt["min_isolated_margin_excess"],
        "settled_wallet_coin": receipt["ending_wallet"],
        "starting_wallet_coin": receipt["starting_wallet"],
        "ending_unrealized_coin": str(observed_open),
        "total_marked_pnl_coin_after_fees_funding_and_execution": str(
            terminal_equity - initial - total_turnover * Decimal(str(EXECUTION))
        ),
        "max_quote_age_used_seconds": max(ages, default=0),
        "orders_above_15_seconds": sum(a > 15 for a in ages),
        "inverse_wallet_identity_error_coin": str(
            terminal_equity - settled - observed_open
        ),
    }
    return ledger, usd_marks, evidence


def metric_row(market, day, profile, trades, further_exposure, equity, source):
    values = summarize(
        ("KuMEX inverse DCA", "定投策略", market, "Observed top-of-book model"),
        day + " 02:00–10:00 UTC",
        [row[:4] for row in trades],
        further_exposure,
    )
    scale = EQUITY / equity
    for name, i in (("gross", 1), ("fee", 2), ("net", 3)):
        value, pct = drawdown((step[0], step[i] * scale) for step in trades)
        values[name + "_dd"], values[name + "_dd_pct"] = value / scale, pct
    values.update(
        id=IDENT,
        source=source,
        interval="1m",
        currency=profile,
        quote_currency=profile,
        currency_decimal_places=12 if profile != "USD" else 8,
        starting_equity=equity,
        funding=sum(r[4] for r in trades),
        execution=sum(r[5] for r in trades),
    )
    return values


def finish(target, scratch, output):
    job_path, output_path = target / JOB, target / RECEIPT
    job, receipt = read(job_path), read(output_path)
    assert digest(job_path.read_bytes()) == receipt["job_sha256"]
    assert digest((target / FIXTURE).read_bytes()) == receipt["worker_sha256"]
    assert digest(job["source"].encode()) == job["source_sha256"]
    probe = read(target / "round3-isolation-python.json")
    assert probe["file_error"][0] == probe["network_error"][0] == "PermissionError"
    incident = read(scratch / "r17-kumex-capture-metadata.json")
    assert all(x["to"] < "2026-10-01" for x in incident["incidentReports"])
    by_key = {(x["symbol"], x["day"]): x for x in receipt["results"]}
    evidence, results, converted, paired = [], [], [], {}
    for case in job["tapes"]:
        key = case["symbol"], case["day"]
        native = by_key[key]
        with localcontext() as ctx:
            ctx.prec = 40
            ledger, usd_marks, observation = verify_ledger(case, native)
        open_qty = abs(observation["ending_open_contracts"])
        asset = "BTC" if key[0] == "XBTUSDM" else "ETH"
        results.append(
            metric_row(
                key[0] + " [" + asset + " settlement]",
                key[1],
                asset,
                ledger,
                open_qty,
                float(observation["starting_wallet_coin"]),
                job["archive"],
            )
        )
        results[-1].update(
            mark_to_market_net=float(
                observation["total_marked_pnl_coin_after_fees_funding_and_execution"]
            ),
            remaining_unrealized=float(observation["ending_unrealized_coin"]),
        )
        converted.append(
            metric_row(
                key[0] + " [USD marked conversion]",
                key[1],
                "USD",
                usd_marks,
                open_qty,
                EQUITY,
                job["archive"],
            )
        )
        paired[key] = usd_marks, open_qty
        evidence.append(
            {
                "instrument": key[0],
                "day": key[1],
                "from_utc": case["start"],
                "to_utc": case["end"],
                "contract_specs": case["spec"],
                "provider_receipts": case["receipts"],
                **observation,
                "stricter_15s_stress": "Would reject an observed initial entry quote"
                if observation["orders_above_15_seconds"]
                else "All quotes used satisfy the tighter age threshold.",
            }
        )
    assert len(evidence) == len(paired) == len(results) == 4
    assert all(x["executed_market_orders"] >= 1 for x in evidence)
    sensitivity = read(scratch / "fmz-kumex-dca-round17-work.json")
    legacy_upnl = Decimal("-0.00014735")
    legacy_basis = Decimal("0.00266375")
    documented_pct = (legacy_upnl / legacy_basis).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    assert documented_pct == Decimal("-0.0553")
    days = sorted({k[1] for k in paired})
    for day in days:
        btc, open_btc = paired["XBTUSDM", day]
        eth, open_eth = paired["ETHUSDM", day]
        converted.append(
            metric_row(
                "XBTUSDM + ETHUSDM [USD marked conversion]",
                day,
                "USD",
                btc + eth,
                open_btc + open_eth,
                2 * EQUITY,
                job["archive"],
            )
        )
    write(
        output,
        {
            "coverage": [
                [
                    IDENT,
                    "Tested · KuMEX inverse archived driver on four exact book scopes",
                    "The published 1-minute/1 short/20x/3% driver ran offline using the legacy raw unrealisedPnlPcnt field and exact BTC/ETH coin-margined books, mark and funding. Four complete scopes each opened one short. No threshold triggered a close during the sampled dates. Win rate is undefined. Native marked open P&L is supplied separately.",
                ]
            ],
            "results": results,
            "usd_mark_conversion_study": converted,
            "leveraged_roe_sensitivity": {
                "scope": "Alternative reads leverage-adjusted return instead of the archived raw position P&L ratio. Its records are a sensitivity and outside the workbook strategy results.",
                "prior_isolation_receipt_sha256": sensitivity["raw_receipt_sha256"],
                "results": sensitivity["results"],
                "usd_mark_conversion_study": sensitivity["usd_mark_conversion_study"],
            },
            "legacy_pnl_field_numeric_fixture": {
                "venue_example": "https://github.com/Kucoin/kucoin-futures-api-docs/diffs/1?commit=aaa0f168589f887f4496502ad4ad7546f9934f0c&name=main&sha1=fe17b1ff2abd03b27e2faa688828bd7d00409499&sha2=aaa0f168589f887f4496502ad4ad7546f9934f0c&short_path=732ed9a&w=false#L3940",
                "inverse_position_cost": str(legacy_basis),
                "inverse_unrealised_pnl": str(legacy_upnl),
                "documented_raw_position_percentage_four_decimals": str(documented_pct),
                "verified_threshold_bound": "Unrounded versus four-decimal rounded legacy ratios agree at every decision.",
            },
            "evidence": evidence,
            "source": {
                "page": PUBLISHER,
                "archive": job["archive"],
                "sha256": job["document_sha256"],
                "code": job["source_sha256"],
            },
            "compact_input_sha256": job["tape_sha256"],
            "raw_receipt_sha256": digest(output_path.read_bytes()),
            "worker_sha256": receipt["worker_sha256"],
            "isolation": probe,
            "capture_metadata": incident,
            "execution_model": {
                "price": "Immediate fully visible best bid/ask at each decision using the latest captured L2 book state. Depth must cover the full requested size. All results are historical simulations.",
                "mark": "The most recent fully closed one-minute KuCoin mark candle. Independently check margin sufficiency against its adverse extreme throughout the held interval.",
                "position": "One-way netting, no reduce-only flag. A larger opposing order can reverse after closing the existing balance.",
                "fees": "Public current taker rate from the exact contract. Fee arithmetic uses full decimal precision and reports 8-decimal upward rounding sensitivity separately.",
                "funding": "Apply official settlement rate to signed position and mark value. Net realized P&L uses per-close allocated funding and benchmark slippage.",
                "trigger": "Legacy unrealisedPnlPcnt is inverse unrealized P&L divided by opening position value. Leverage applies to collateral and margin checks.",
                "currency": "Workbook rows retain native BTC or ETH settlement. The separate marked conversion study derives USD equivalent from each close's contemporaneous mark. Closing wallet and unrealized P&L use native settlement units.",
                "scope": "Source instrument is configurable. Settings follow the author, with separate flat starting portfolios of 10,000 USD-equivalent collateral. Each scope is a fixed 8-hour first-of-month sample elected before outcome inspection.",
            },
            "references": [
                "https://docs.tardis.dev/faq/data",
                "https://docs.tardis.dev/historical-data-details/kucoin-futures",
                "https://www.kucoin.com/support/27703947513497",
                "https://www.kucoin.com/support/26693238981785",
                "https://www.kucoin.com/support/48142946141509",
                "https://raw.githubusercontent.com/Kucoin/kumex-go-sdk/master/position.go",
                "https://www.kucoin.com/docs-new/rest/futures-trading/positions/get-position-details",
            ],
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("compact", type=Path)
    p.add_argument("target", type=Path)
    p.add_argument("--finish", type=Path)
    a = p.parse_args()
    if a.finish:
        finish(a.target, a.compact.parent, a.finish)
    else:
        stage(a.archive, a.compact, a.target)
