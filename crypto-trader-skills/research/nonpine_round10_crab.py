"""Replay a source-backed Opyn Crab share through observed shutdown redemption."""

import argparse
import hashlib
from collections import Counter
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from statistics import median_low

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics
from research.nonpine_round8_squeeth import (
    FEE_SCALE,
    POOL,
    POOL_FEE,
    REV,
    SWAP_TOPIC,
    WAD,
    block_position,
    decode_data,
    gas_wei,
)

CRAB = "0x3b960e47784150f5a63777201ee2b15253d713e8"
SHUTDOWN = 21_115_343


def payout_wei(shares, ratio):
    return shares * ratio.numerator // ratio.denominator


def flow_wei(deposit, swap_in, swap_out, minted, redemption):
    if not 0 < minted <= swap_in or min(deposit, swap_out, redemption) <= 0:
        raise ValueError("Invalid observed cash flow or unavailable short sale size")
    net_sale = minted * swap_out // swap_in
    gross_sale = net_sale * FEE_SCALE // (FEE_SCALE - POOL_FEE)
    return net_sale, gross_sale + redemption - deposit, gross_sale - net_sale


def build(folder):
    names = {
        "deposit": "crab-deposit-early.json",
        "transaction": "crab-deposit-transaction.json",
        "swap": "squeeth-swaps-early.json",
        "withdrawal": "crab-shutdown-withdraw.json",
    }
    files = {key: folder / name for key, name in names.items()}
    data = {key: read(path) for key, path in files.items()}
    assert all(data[k]["status"] == "1" for k in ("deposit", "swap", "withdrawal"))
    (entry,) = data["deposit"]["result"]
    transaction = data["transaction"]
    assert entry["address"].lower() == CRAB
    assert transaction["to"]["hash"].lower() == CRAB and transaction["status"] == "ok"
    assert transaction["hash"].lower() == entry["transactionHash"].lower()
    assert entry["topics"][1][-40:].lower() == transaction["from"]["hash"][-40:].lower()
    assert int(transaction["fee"]["value"]) == gas_wei(entry)
    assert block_position(entry)[0] < SHUTDOWN
    minted, shares = decode_data(entry["data"], ("uint256", "uint256"))
    assert min(minted, shares) > 0
    deposit = int(transaction["value"])

    observed = []
    for log in data["swap"]["result"]:
        assert log["address"].lower() == POOL and log["topics"][0] == SWAP_TOPIC
        if (
            block_position(entry) < block_position(log)
            and block_position(log)[0] < SHUTDOWN
        ):
            weth, squeeth, *_ = decode_data(
                log["data"], ("int256", "int256", "uint160", "uint128", "int24")
            )
            if weth < 0 and squeeth >= minted:
                observed.append((log, squeeth, -weth))
    swap, swap_in, swap_out = min(observed, key=lambda row: block_position(row[0]))

    logs = data["withdrawal"]["result"]
    counts = Counter(log["transactionHash"] for log in logs)
    assert 5 <= len(logs) < 1000
    ratios, redemption_fees = [], []
    for log in logs:
        assert log["address"].lower() == CRAB and block_position(log)[0] > SHUTDOWN
        burned, paid = decode_data(log["data"], ("uint256", "uint256"))
        assert min(burned, paid) > 0
        ratios.append(Fraction(paid, burned))
        if counts[log["transactionHash"]] == 1:
            redemption_fees.append(gas_wei(log))
    low, high = min(ratios), max(ratios)
    assert high - low < Fraction(1, 10**13)
    payout = payout_wei(shares, low)
    exit_gas = median_low(redemption_fees)
    network_cost = gas_wei(entry) + gas_wei(swap) + exit_gas
    sale, gross, fee = flow_wei(deposit, swap_in, swap_out, minted, payout)

    entered = int(entry["timeStamp"], 16)
    hedged = int(swap["timeStamp"], 16)
    redeemed = min(int(log["timeStamp"], 16) for log in logs)
    assert entered < hedged < redeemed
    summary = metrics([(redeemed, gross / WAD, fee / WAD, network_cost / WAD)])
    summary["net_dd_pct"] = summary["net_dd"] / (deposit / WAD)
    open_day = datetime.fromtimestamp(entered, UTC).date().isoformat()
    close_day = datetime.fromtimestamp(redeemed, UTC).date().isoformat()
    return {
        "coverage": [
            [
                6173,
                "Tested · Historical Opyn Crab isolated liquidity scenario",
                (
                    "Actual ETH deposit and Crab mint, later sufficient-sized observed oSQTH sale, "
                    "and bounded payout from 31 shutdown redemptions. "
                    "Single historical lot with pro-rata hedge proceeds and modeled redemption gas."
                ),
            ]
        ],
        "results": [
            {
                "id": 6173,
                "period": f"{open_day} to {close_day} UTC",
                "group": "Opyn Crab V2 · dated mint, hedge and shutdown scenario",
                "market": "Ethereum Crab V2 (ETH)",
                "currency": "ETH",
                "interval": "Ethereum transaction order",
                "archive_interval": "Mainnet deposit, swap and redemption events",
                "exit": "Observed shutdown redemption rate",
                "order_family": "Crab shares with oSQTH disposal",
                **summary,
            }
        ],
        "source": f"https://github.com/opynfinance/squeeth-monorepo/blob/{REV}/packages/hardhat/contracts/strategy/CrabStrategyV2.sol",
        "archive": "https://eth.blockscout.com/api",
        "source_receipts": {
            key: hashlib.sha256(p.read_bytes()).hexdigest() for key, p in files.items()
        },
        "receipt": {
            "deposit_tx": entry["transactionHash"],
            "hedge_reference_tx": swap["transactionHash"],
            "deposit_time": entered,
            "hedge_time": hedged,
            "redeem_reference_time": redeemed,
            "crab_shares_raw": shares,
            "minted_osqth_raw": minted,
            "deposit_value_wei": deposit,
            "observed_swap_weth_out_wei": swap_out,
            "observed_swap_osqth_in_wei": swap_in,
            "hedge_proceeds_wei": sale,
            "redemptions_audited": len(logs),
            "redeem_rate_min": [low.numerator, low.denominator],
            "redeem_rate_max": [high.numerator, high.denominator],
            "conservative_payout_wei": payout,
            "observed_deposit_gas_wei": gas_wei(entry),
            "observed_reference_swap_gas_wei": gas_wei(swap),
            "modeled_redemption_gas_wei": exit_gas,
            "estimated_nominal_pool_fee_wei": fee,
            "gross_before_fee_wei": gross,
            "net_after_all_costs_wei": gross - fee - network_cost,
        },
        "method": "The observed deposit mints strategy shares and oSQTH. The study disposes of "
        "the contemporaneous oSQTH allocation through the first later observed sufficiently sized pool sale. "
        "The mint and hedge are separate events, with exposure remaining during that delay. "
        "Funds are settled at a conservative rate from actual shutdown redemptions. "
        "The observed sale price already embeds the venue fee and price impact. Gross adds back the nominal "
        "pool fee and the net scenario charges recorded available gas and the historical median redemption gas. "
        "All quotes are ETH, and drawdown uses realized settlement on the observed entry notional.",
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("data_dir", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    write(args.output, build(args.data_dir))
