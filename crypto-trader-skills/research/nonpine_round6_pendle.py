"""Replay resolved Pendle strategy legs from archived swaps and paired LP receipts."""

import argparse
import hashlib
import json
from pathlib import Path

from .nonpine_round4_metrics import metrics
from .nonpine_round5_pendle import API, MARKETS, SWAP, spot_close, unix_ms
from .nonpine_round6_protocol import TRANSFER, Evidence, decode

WAD = 10**18
MINT_LP = "0xb4c03061fb5b7fed76389d5af8f2e0ddb09f8c70d1333abbb62582835e10accb"
BURN_LP = "0x4cf25bc1d991c17529c25213d3cc0cda295eeaad5f13f361969b12ea48015f90"
MINT_YIELD = "0xc0025304673122449dd60b9b0093874b0e2fd6fe57af1c7c2fbfee0ccf5ead58"
BURN_YIELD = "0x5d624aa9c148153ab3446c1b154f660ee7701e549fe9b62dab7171b1c80e6fa2"
YT_CLAIM_GAS = 175_000
PT_REDEMPTION_GAS = 200_000
MINT_SY_GAS = 240_000


def accrued_interest(principal, starting, ending):
    assert ending >= starting > 0 and principal > 0
    return principal * (ending - starting) * WAD // (starting * ending)


def signed_hex(data, signed=0):
    raw = bytes.fromhex(data.removeprefix("0x"))
    assert len(raw) % 32 == 0
    return [
        int.from_bytes(raw[i : i + 32], "big", signed=i < signed * 32)
        for i in range(0, len(raw), 32)
    ]


def address(meta, key):
    return meta[key].split("-")[-1].lower()


def asset_flow(receipt, token, owner):
    net = 0
    for log in receipt["logs"]:
        if log["address"] == token and log["topics"][:1] == [TRANSFER]:
            assert len(log["topics"]) == 3
            _, source, destination = log["topics"]
            delta = int(log["data"], 16)
            net += (
                ("0x" + destination[-40:] == owner) - ("0x" + source[-40:] == owner)
            ) * delta
    return net


def event_flows(meta, receipt, owner):
    pendle = {key: address(meta, key) for key in ("sy", "pt", "yt")}
    market = meta["address"]
    topics = {
        MINT_LP: ("M", 0),
        BURN_LP: ("B", 0),
        SWAP: ("S", 2),
        MINT_YIELD: ("M", 0),
        BURN_YIELD: ("B", 0),
    }
    flows = ([], [])
    for item in receipt["logs"]:
        if item["address"] not in (market, pendle["yt"]):
            continue
        label = topics.get(item["topics"][0])
        if label is None:
            continue
        point = 0 if item["address"] == market else 1
        flow_type, signed = label
        flows[point].append((flow_type, signed_hex(item["data"], signed)))
    tokens = dict(pendle, lp=market)
    return *flows, {
        key: asset_flow(receipt, addr, owner) for key, addr in tokens.items()
    }


def close_mark(evidence, coin, stamp):
    month = stamp[:7]
    name = f"pendle-spot/{coin}USDT-1m-{month}.zip"
    if not (evidence.path / name).is_file():
        name = f"pendle-spot/{coin}USDT-1m-{stamp[:10]}.zip"
    if name not in evidence.prices:
        data = evidence.path / name
        evidence.samples[name] = hashlib.sha256(data.read_bytes()).hexdigest()
        evidence.prices[name] = spot_close(data)
    stamp_ms = unix_ms(stamp)
    return evidence.prices[name][stamp_ms // 60_000 * 60_000 - 60_000]


def observed_inputs(evidence, coin, meta, kind):
    observed = []
    for row in evidence.document(f"pendle-{coin.lower()}-{kind}.json")["results"]:
        if not row["isClearAction"]:
            continue
        tx = row["txHash"]
        key = f"pendle-receipts/{tx}.json"
        if not (evidence.path / key).is_file():
            continue
        receipt = evidence.result(key)
        assert receipt["status"] == "0x1" and receipt["transactionHash"] == tx
        assert row["action"] == kind and row["chainId"] == 1
        assert row["market"] == "1-" + meta["address"]
        assert receipt["from"].lower() == row["txOrigin"].lower()
        flows = event_flows(meta, receipt, row["txOrigin"].lower())
        observed.append((row, *flows, receipt))
    return observed


def entry_price(evidence, coin, scale, stamp, index):
    return close_mark(evidence, coin, stamp) * index / WAD / scale


def gas_price(evidence, receipt, stamp):
    return (
        int(receipt["effectiveGasPrice"], 16) * close_mark(evidence, "ETH", stamp) / WAD
    )


def index_at_tx(evidence, tx):
    return int(evidence.result(f"pendle-index-{tx}.json"), 16)


def yield_buys(evidence, coin, scale, meta):
    expiry = meta["expiry"]
    end_index = decode(
        evidence.result(f"pendle-{coin.lower()}-getPostExpiryData.json")
    )[0]
    rates = [
        int(evidence.result(f"pendle-{coin.lower()}-interestFeeRate{suffix}.json"), 16)
        for suffix in ("", "-BUY_YT", "-REMOVE_LIQUIDITY")
    ]
    assert rates[0] == rates[1] == rates[2] and 0 <= rates[0] < WAD
    fee_rate = rates[0]
    ledgers = []
    for row, swaps, yield_ops, wallet, receipt in observed_inputs(
        evidence, coin, meta, "BUY_YT"
    ):
        tx, stamp = row["txHash"], row["timestamp"]
        if len(ledgers) >= 10:
            break
        if not (stamp < expiry and len(swaps) == 1 and swaps[0][0] == "S"):
            continue
        if [name for name, _ in yield_ops] != ["M"] or any(
            wallet[a] for a in ("lp", "pt", "sy")
        ):
            continue
        (sy_minted, quantity) = yield_ops[0][1]
        lost_pt, sy_from_lp, swap_fee, reserve = swaps[0][1]
        if not (
            quantity == wallet["yt"] > 0 and lost_pt < 0 and 0 < sy_from_lp < sy_minted
        ):
            continue
        assert 0 <= reserve <= swap_fee
        assert abs(quantity + lost_pt) <= max(8, quantity // 10**6)
        index = index_at_tx(evidence, tx)
        if abs(sy_minted * index // WAD - quantity) > max(3, quantity // 10**6):
            continue
        sy_payout = accrued_interest(quantity, index, end_index)
        entry_usd = entry_price(evidence, coin, scale, stamp, index)
        exit_usd = entry_price(evidence, coin, scale, stamp, end_index)
        gross = sy_payout * exit_usd - (sy_minted - sy_from_lp - swap_fee) * entry_usd
        fees = swap_fee * entry_usd + (sy_payout * fee_rate // WAD) * exit_usd
        gas_unit = gas_price(evidence, receipt, stamp)
        gas = (int(receipt["gasUsed"], 16) + YT_CLAIM_GAS) * gas_unit
        ledgers.append(
            {
                "entry_tx": tx,
                "opened": stamp,
                "closed": expiry,
                "quantity_yt": quantity,
                "sy_in": sy_minted - sy_from_lp,
                "index_entry": index,
                "index_maturity": end_index,
                "sy_interest_before_fee": sy_payout,
                "source_interest_fee_rate": fee_rate,
                "sy_pool_fee": swap_fee,
                "entry_value_usdt": (sy_minted - sy_from_lp) * entry_usd,
                "pnl": [gross, fees, gas],
            }
        )
    return ledgers


def stripped_yield(evidence, coin, scale, meta):
    expiry = meta["expiry"]
    ledgers = []
    for row, swaps, yield_ops, wallet, receipt in observed_inputs(
        evidence, coin, meta, "SELL_YT"
    ):
        tx, stamp = row["txHash"], row["timestamp"]
        if row["value"] > 1800 or not (
            stamp < expiry and len(swaps) == 1 and swaps[0][0] == "S"
        ):
            continue
        if not yield_ops or any(name != "B" for name, _ in yield_ops):
            continue
        if any(wallet[a] for a in ("pt", "sy", "lp")):
            continue
        pt_acquired, sy_spent, swap_fee, reserve = swaps[0][1]
        sold = -wallet["yt"]
        if not (sold == pt_acquired > 0 and sum(v[0] for _, v in yield_ops) == sold):
            continue
        assert sy_spent < 0 and 0 <= reserve <= swap_fee
        sy_from_paired_redemption = sum(v[1] for _, v in yield_ops)
        residual_sale = sy_from_paired_redemption + sy_spent
        if residual_sale <= 0:
            continue
        index = index_at_tx(evidence, tx)
        if abs((sold * WAD // index) - sy_from_paired_redemption) > max(
            8, sold // 10**6
        ):
            continue
        sy_to_mint = (sold * WAD + index - 1) // index
        usd_per_asset_unit = close_mark(evidence, coin, stamp) / scale
        usd_per_sy_unit = usd_per_asset_unit * index / WAD
        gross = (
            sold * usd_per_asset_unit
            + (residual_sale + swap_fee - sy_to_mint) * usd_per_sy_unit
        )
        fees = swap_fee * usd_per_sy_unit
        gas = (
            int(receipt["gasUsed"], 16) + MINT_SY_GAS + PT_REDEMPTION_GAS
        ) * gas_price(evidence, receipt, stamp)
        ledgers.append(
            {
                "yt_sale_tx": tx,
                "opened": stamp,
                "closed": expiry,
                "pt_retained": sold,
                "sy_to_mint": sy_to_mint,
                "sy_yield_sale": residual_sale,
                "pool_fee_sy": swap_fee,
                "entry_value_usdt": sy_to_mint * usd_per_sy_unit,
                "pnl": [gross, fees, gas],
            }
        )
    return ledgers


def paired_liquidity(evidence, coin, scale, meta):
    candidates = {}
    for row, ops, yield_ops, wallet, receipt in observed_inputs(
        evidence, coin, meta, "ADD_LIQUIDITY"
    ):
        if row["value"] > 9000 or [name for name, _ in ops] != ["S", "M"] or yield_ops:
            continue
        if (
            any(wallet[a] for a in ("pt", "sy", "yt"))
            or not ops[1][1][0] == wallet["lp"] > 0
        ):
            continue
        candidates[(row["txOrigin"], wallet["lp"])] = (row, ops, receipt)
    ledgers = []
    for row, ops, yield_ops, wallet, receipt in observed_inputs(
        evidence, coin, meta, "REMOVE_LIQUIDITY"
    ):
        if len(ledgers) >= 5:
            break
        if [name for name, _ in ops] != ["B"] or [name for name, _ in yield_ops] != [
            "B"
        ]:
            continue
        if any(wallet[a] for a in ("pt", "sy", "yt")):
            continue
        partner = candidates.get((row["txOrigin"], -wallet["lp"]))
        if not partner or partner[0]["timestamp"] >= row["timestamp"]:
            continue
        initial, entry_ops, entry_receipt = partner
        tx_in, tx_out = initial["txHash"], row["txHash"]
        if not all(
            (evidence.path / f"pendle-index-{tx}.json").is_file()
            for tx in (tx_in, tx_out)
        ):
            continue
        shares, sy_out, pt_out = ops[0][1]
        pt_burned, sy_redeemed = yield_ops[0][1]
        assert shares == -wallet["lp"] > 0 and sy_out > 0
        if pt_burned != pt_out:
            continue
        _, sy_spent, pool_fee, _ = entry_ops[0][1]
        _, sy_add, _ = entry_ops[1][1]
        assert sy_spent < 0 and 0 <= pool_fee <= -sy_spent
        index_start = index_at_tx(evidence, tx_in)
        index_end = index_at_tx(evidence, tx_out)
        price_start = entry_price(
            evidence, coin, scale, initial["timestamp"], index_start
        )
        price_end = entry_price(evidence, coin, scale, initial["timestamp"], index_end)
        entry_value = (sy_add - sy_spent) * price_start
        if entry_value > 10_000 or entry_value <= 0:
            continue
        if sum(l["entry_value_usdt"] for l in ledgers) + entry_value > 10_000:
            continue
        fees = pool_fee * price_start
        gross = (sy_out + sy_redeemed) * price_end - entry_value + fees
        costs = 0.0
        for tx_receipt, event in ((entry_receipt, initial), (receipt, row)):
            costs += int(tx_receipt["gasUsed"], 16) * gas_price(
                evidence, tx_receipt, event["timestamp"]
            )
        ledgers.append(
            {
                "entry_tx": tx_in,
                "exit_tx": tx_out,
                "opened": initial["timestamp"],
                "closed": row["timestamp"],
                "minted_and_redeemed_lp": shares,
                "sy_in": sy_add - sy_spent,
                "sy_received": sy_out + sy_redeemed,
                "index_entry": index_start,
                "index_exit": index_end,
                "pool_fee_sy": pool_fee,
                "entry_value_usdt": entry_value,
                "pnl": [gross, fees, costs],
            }
        )
    return ledgers


def summarize(strategy, label, exit_rule, ledger, coin, wrapper):
    active = f"{min(x['opened'][:10] for x in ledger)} through {max(x['closed'][:10] for x in ledger)}"
    return {
        "id": strategy,
        "period": active,
        "group": f"Pendle · {label}",
        "exit": exit_rule,
        "market": f"{coin} {wrapper} (USDT)",
        "currency": "USDT",
        "interval": "Ethereum market events",
        "archive_interval": "Actual on-chain receipts and PY indexes",
        "order_family": label,
        **metrics([(unix_ms(x["closed"]), *x["pnl"]) for x in ledger]),
    }


def replay(path, base):
    evidence = Evidence(path)
    study = {
        6148: ("YT accrued interest", "Finalized PY index at expiry", yield_buys),
        6149: (
            "Exact LP share-lot carry",
            "Exact matching LP share burn",
            paired_liquidity,
        ),
        6150: (
            "Strip and sell YT carry",
            "Retained PT settles at accounting par",
            stripped_yield,
        ),
    }
    results, ledger = [], {}
    for coin, (wrapper, _, market, scale, page) in MARKETS.items():
        metadata_path = base / f"pendle-{page}.json"
        source = metadata_path.read_bytes()
        evidence.samples[f"{API}/v2/markets/all?limit=100&skip={page}"] = (
            hashlib.sha256(source).hexdigest()
        )
        meta = next(r for r in json.loads(source)["results"] if r["address"] == market)
        assert meta["chainId"] == 1
        for ident, (label, exit_rule, method) in study.items():
            rows = method(evidence, coin, scale, meta)
            ledger[f"{ident}-{coin}"] = rows
            if rows:
                results.append(summarize(ident, label, exit_rule, rows, coin, wrapper))
    assert {x["id"] for x in results} == set(study)
    return {
        "coverage": [
            [
                6148,
                "Tested · Pendle YT accrued interest",
                (
                    "Thirteen actual YT buys on LBTC and wstETH pools. PT swap and tokenization "
                    "receipts reconstruct entry, contract PY index changes reconstruct interest, "
                    "and verified factory fee plus actual entry gas and modeled claim gas are charged. "
                    "Carries underlying index only, with incentive tokens excluded."
                ),
            ],
            [
                6149,
                "Tested · Pendle paired LP share lots",
                (
                    "Nine exact-size LP mint/burn lots paired by ownership and pool across LBTC and wstETH. "
                    "Market and yield token logs price committed SY, received SY, swap fee and both receipt gas costs. "
                    "Pool cashflows are converted at entry accounting-asset reference; incentives excluded."
                ),
            ],
            [
                6150,
                "Tested · Pendle strip-yield receipt variant",
                (
                    "Six BTC-linked YT disposals reconcile to PT/SY swap and paired redemption logs. "
                    "Modeled tokenization uses the event PY index and matches observable YT sale size. "
                    "Retained PT settles at modeled accounting par; fees and representative mint/redeem gas included. "
                    "The single ETH sale was mixed with LP withdrawal and cannot establish a comparable ETH result."
                ),
            ],
        ],
        "results": results,
        "ledger": ledger,
        "evidence_sha256": dict(sorted(evidence.samples.items())),
        "settings": {
            "documented_api": "https://docs.pendle.finance/pendle-v2-dev/Backend/ApiOverview",
            "market_cashflows": "https://github.com/pendle-finance/pendle-core-v2-public/blob/main/contracts/interfaces/IPMarket.sol",
            "interest_math": "https://github.com/pendle-finance/pendle-core-v2-public/blob/main/contracts/core/YieldContracts/InterestManagerYT.sol",
            "carry_proxy": "Underlying accounting asset at entry spot; no collateral directional P&L, wrapper basis, or standalone reward token P&L.",
            "gas": "Observed effective gas and used amounts for actual legs. Fixed gas units for modeled mint, claim or redeem legs valued at contemporaneous entry price.",
            "modeled_mint_gas": MINT_SY_GAS,
            "modeled_yt_claim_gas": YT_CLAIM_GAS,
            "modeled_pt_redemption_gas": PT_REDEMPTION_GAS,
            "archive_state": "https://eth.drpc.org",
            "receipt_source": "https://ethereum.public.blockpi.network/v1/rpc/public",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("previous_input", type=Path)
    parser.add_argument("output", type=Path)
    opts = parser.parse_args()
    report = replay(opts.input, opts.previous_input)
    opts.output.write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf8",
        newline="\n",
    )
    for row in report["results"]:
        print(row["id"], row["market"], row["trades"], row["net"])


if __name__ == "__main__":
    main()
