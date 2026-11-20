"""Reproduce Opyn oSQTH long through shutdown using observed pool trades."""

import argparse
import hashlib
from collections import Counter
from pathlib import Path
from statistics import median_low

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics

WAD = 10**18
FEE_SCALE = 10**6
POOL_FEE = 3000
POOL = "0x82c427adfdf2d245ec51d8046b41c4ee87f0d29c"
CONTROLLER = "0x64187ae08781b09368e6253f9e94951243a493d5"
REV = "10e70837705a1fffbb543ecc825e337c373dc498"
ARCHIVE = "https://eth.blockscout.com/api"
SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
TOPICS = {
    "shutdown": "0x574214b195bf5273a95bb4498e35cf1fde0ce327c727a95ec2ab359f7ba4e11a",
    "norm": "0x339e53729b0447795ff69e70a74fed98fc7fef6fe94b7521099b32f0f8de4822",
    "redeem": "0x2131ef4f2f82ca75fe7d2e646ebfa45b6be25e53510c829629c76b641500ec67",
    "trades-pre": SWAP_TOPIC,
    "trades-earlier": SWAP_TOPIC,
}
SOURCES = {
    "shutdown": (CONTROLLER, "Shutdown(uint256)", 21115310, 21115370),
    "norm": (
        CONTROLLER,
        "NormalizationFactorUpdated(uint256,uint256,uint256,uint256)",
        21112340,
        21115370,
    ),
    "redeem": (
        CONTROLLER,
        "RedeemLong(address,uint256,uint256)",
        21115340,
        21136340,
    ),
    "trades-pre": (
        POOL,
        "Swap(address,address,int256,int256,uint160,uint128,int24)",
        21108340,
        21115339,
    ),
    "trades-earlier": (
        POOL,
        "Swap(address,address,int256,int256,uint160,uint128,int24)",
        21091340,
        21101340,
    ),
}


def decode_data(hex_value, kinds):
    raw = bytes.fromhex(hex_value.removeprefix("0x"))
    if len(raw) != len(kinds) * 32:
        raise ValueError("Unexpected log payload length")
    return tuple(
        int.from_bytes(raw[pos : pos + 32], "big", signed=kind.startswith("int"))
        for pos, kind in zip(range(0, len(raw), 32), kinds, strict=True)
    )


def settlement_wei(shares, normalization, index):
    return shares * normalization * index // (WAD * WAD)


def block_position(log):
    return tuple(int(log[key], 16) for key in ("blockNumber", "logIndex"))


def gas_wei(log):
    return int(log["gasUsed"], 16) * int(log["gasPrice"], 16)


def sample_data(folder):
    evidence, entries = {}, {}
    for name, (contract, event, lo, hi) in SOURCES.items():
        file = folder / f"{name}.json"
        response = read(file)
        assert response["status"] == "1"
        logs = sorted(response["result"], key=block_position)
        assert 0 < len(logs) < 1000
        assert len({block_position(log) for log in logs}) == len(logs)
        assert all(log["address"].lower() == contract for log in logs)
        assert all(lo <= block_position(log)[0] <= hi for log in logs)
        assert {log["topics"][0] for log in logs} == {TOPICS[name]}
        entries[name] = logs
        evidence[name] = {
            "contract": contract,
            "event": event,
            "topic0": logs[0]["topics"][0],
            "block_range": [lo, hi],
            "events": len(logs),
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        }
    return entries, evidence


def build(folder):
    entries, evidence = sample_data(folder)
    (shutdown,) = entries["shutdown"]
    (index,) = decode_data(shutdown["data"], ("uint256",))
    latest = max(
        (
            log
            for log in entries["norm"]
            if block_position(log) < block_position(shutdown)
        ),
        key=block_position,
    )
    _, normalization, _, _ = decode_data(latest["data"], ("uint256",) * 4)
    redeem_tx_counts = Counter(e["transactionHash"] for e in entries["redeem"])
    redemption_costs = []
    for log in entries["redeem"]:
        _, burned, payout = decode_data(log["data"], ("address", "uint256", "uint256"))
        assert block_position(log) > block_position(shutdown)
        assert settlement_wei(burned, normalization, index) == payout
        if burned and redeem_tx_counts[log["transactionHash"]] == 1:
            redemption_costs.append(gas_wei(log))
    assert len(redemption_costs) >= 5
    exit_cost = median_low(redemption_costs)

    timestamp = int(shutdown["timeStamp"], 16)
    results, observed = [], {}
    for name in ("trades-earlier", "trades-pre"):
        logs = entries[name]
        tx_counts = Counter(log["transactionHash"] for log in logs)
        positions, receipts = [], []
        for log in logs:
            input_weth, out_squeeth, *_ = decode_data(
                log["data"], ("int256", "int256", "uint160", "uint128", "int24")
            )
            assert block_position(log) < block_position(shutdown)
            if (
                input_weth <= 0
                or out_squeeth >= 0
                or tx_counts[log["transactionHash"]] != 1
            ):
                continue
            shares = -out_squeeth
            proceeds = settlement_wei(shares, normalization, index)
            assert proceeds > 0
            fee = (input_weth * POOL_FEE + FEE_SCALE - 1) // FEE_SCALE
            network = gas_wei(log) + exit_cost
            positions.append(
                (
                    timestamp,
                    (proceeds - input_weth + fee) / WAD,
                    fee / WAD,
                    network / WAD,
                )
            )
            receipts.append(
                {
                    "tx": log["transactionHash"],
                    "block": block_position(log)[0],
                    "log_index": block_position(log)[1],
                    "weth_spent_wei": input_weth,
                    "shares": shares,
                    "settlement_wei": proceeds,
                    "modeled_pool_fee_wei": fee,
                    "observed_entry_gas_wei": gas_wei(log),
                    "modeled_redemption_gas_wei": exit_cost,
                }
            )
        assert receipts
        observed[name] = receipts
        result = metrics(positions)
        paid_wei = sum(x["weth_spent_wei"] for x in receipts)
        result["net_dd_pct"] = result["net_dd"] / (paid_wei / WAD)
        results.append(
            {
                "id": 6172,
                "period": "2024-11-01/02 entry"
                if name == "trades-earlier"
                else "2024-11-03/04 entry",
                "group": "Opyn long oSQTH · observed swap-to-shutdown scenarios",
                "market": "Ethereum oSQTH/WETH (ETH)",
                "currency": "ETH",
                "interval": "Ethereum swap receipts and shutdown settlement",
                "archive_interval": "Mainnet transaction order",
                "exit": "Protocol shutdown settlement",
                "order_family": "Long oSQTH with fixed shutdown exit",
                **result,
            }
        )
    return {
        "coverage": [
            [
                6172,
                "Tested · Historical Opyn long oSQTH shutdown variant",
                (
                    "Independent observed WETH-to-oSQTH buys held to the actual shutdown index "
                    "and integer share payout, verified against on-chain redemptions. "
                    "Entry transaction gas observed, redemption gas and pool fee allocation modeled."
                ),
            ]
        ],
        "results": results,
        "provenance": {
            "source_revision": REV,
            "public_contract": f"https://github.com/opynfinance/squeeth-monorepo/blob/{REV}/packages/hardhat/contracts/core/Controller.sol",
            "archive_endpoint": ARCHIVE,
            "logs": evidence,
            "shutdown_block": block_position(shutdown)[0],
            "shutdown_tx": shutdown["transactionHash"],
            "normalization": normalization,
            "settlement_index": index,
            "redemptions_reconciled": len(entries["redeem"]),
            "redemption_gas_samples": len(redemption_costs),
            "redemption_gas_wei": exit_cost,
            "pool_fee_ppm": POOL_FEE,
        },
        "receipts": observed,
        "method": "Quotes are in ETH. Each qualifying observation starts at the observed swap's native "
        "size and WETH cost and holds to the single controller settlement. Gross adds back "
        "the nominal fee; tick rounding and exact fee partition are not reconstructed. Net adds "
        "observed entry gas and the lower median of single-redemption receipt gas. "
        "Maximum drawdown uses realized outcomes at settlement, with total WETH spent "
        "as the percentage denominator. This is a retrospective set of independent scenarios.",
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("data_dir", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    write(args.output, build(args.data_dir))
