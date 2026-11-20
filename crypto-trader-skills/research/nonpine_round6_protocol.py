"""Offline replays of archived Ethereum vault and redemption observations."""

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from .nonpine_round4_metrics import metrics
from .nonpine_round5_pendle import spot_close

RIBBON_FEE = "0x0a242f7ecaf711036ca770774ceffae28e60ef042ac113ddd187f2631db0c006"
REDEMPTION = "0x43a3f4082a4dbc33d78e317d2497d3a730bc7fc3574159dcea1056e62e5d9ad8"
TROVE = "0xa39739ef8b0231dbfa0dcda07d7e29faabcf4bb2"
STABILITY_POOL = "0x66017d22b0f8556afdD19FC67041899EB65a21bb".lower()
ACTIVE_POOL = "0xdf9eb223bafbe5c5271415c75aecd68c21fe3d7f"
LUSD = "0x5f98805a4e8be255a32880fdec7f6728c6568ba0"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ETHER_SENT = "0x6109e2559dfa766aaec7118351d48a523f0a4157f49c8d68749c8ac41318ad12"
LUSD_UPDATE = "0xa8e886449d8f7e765877b4a4f54632da3943ae454d5a272bdccb1781f086ff29"
VAULTS = {
    "0x25751853eab4d0eb3652b5eb6ecb102a2789644b": (
        6160,
        "ETH call vault (USDT)",
        18,
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    ),
    "0x65a833afdc250d9d38f8cd9bc2b1e3132db13b2f": (
        6160,
        "WBTC call vault (USDT)",
        8,
        "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
    ),
    "0xcc323557c71c0d1d20a1861dc69c06c5f3cc9624": (
        6161,
        "ETH put vault (USDT)",
        6,
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    ),
}
GWEI_SCALE = 10**18  # wei per ETH
RIBBON_GAS = (250_000, 400_000)
ROUTER_GAS = 140_000
SP_DEPOSIT_ABSOLUTE_GAS = 200_000
SP_WITHDRAW_ABSOLUTE_GAS = 275_000
VAULT_NOTIONAL = 1_000
REDEMPTION_SIZE = 1_000 * 10**18
V3_FEE_PPM = 500


def ribbon_return(
    *,
    starting_pps,
    ending_pps,
    vault_fee,
    eligible_shares,
    decimals,
    investment,
    investor_gas,
):
    fee_pps = vault_fee * 10**decimals / eligible_shares
    net_vault = investment * (ending_pps / starting_pps - 1)
    fee = investment * fee_pps / starting_pps
    return net_vault + fee, fee, investor_gas


def redemption_return(entry, exit_gross_eth, exit_net_eth, fee_ppm, gas):
    factor = 1 - fee_ppm / 1_000_000
    assert 0 < factor < 1 and 0 < exit_net_eth <= exit_gross_eth and entry > 0
    gross_exit = exit_gross_eth / factor
    pre_fee_entry = entry * factor
    fees = (gross_exit - exit_net_eth) + (entry - pre_fee_entry)
    return gross_exit - pre_fee_entry, fees, gas


def liquidation_lot(*, lusd_lot, deposited_before, burned_lusd, collateral_eth):
    assert 0 < burned_lusd < deposited_before and 0 < lusd_lot <= deposited_before
    assert collateral_eth > 0
    lusd_remaining = lusd_lot - lusd_lot * burned_lusd // deposited_before
    eth_received = lusd_lot * collateral_eth // deposited_before
    return lusd_remaining, eth_received


def decode(value):
    raw = value.removeprefix("0x")
    assert len(raw) % 64 == 0
    return [int(raw[i : i + 64], 16) for i in range(0, len(raw), 64)]


class Evidence:
    def __init__(self, path):
        self.path = path
        self.samples = {}
        self.prices = {}

    def document(self, name):
        raw = (self.path / name).read_bytes()
        self.samples[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    def result(self, name):
        return self.document(name)["result"]

    def eth_usdt(self, timestamp):
        month = datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m")
        rel = f"ribbon-spot/ETHUSDT-1m-{month}.zip"
        if rel not in self.prices:
            path = self.path / rel
            self.samples[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.prices[rel] = spot_close(path)
        return self.prices[rel][(timestamp // 60 * 60 - 60) * 1_000]


def verify_log(event, receipt):
    assert receipt["status"] == "0x1"
    assert receipt["transactionHash"] == event["transactionHash"]
    assert receipt["blockNumber"] == event["blockNumber"]
    assert receipt["blockHash"] == event["blockHash"]
    [same] = [log for log in receipt["logs"] if log["logIndex"] == event["logIndex"]]
    for field in ("address", "topics", "data"):
        assert same[field] == event[field]


def ribbon_receipt(evidence, event):
    addr = event["address"]
    ident, market, decimals, collateral = VAULTS[addr]
    block = int(event["blockNumber"], 16)
    prefix = f"ribbon-states/{addr[2:10]}-{block}"
    _, total_fee, round_id = decode(event["data"])

    def result(label):
        return evidence.result(f"{prefix}-{label}.json")

    receipt = result("receipt")
    verify_log(event, receipt)
    state = decode(result("previous-state"))
    supply = int(result("prior-supply"), 16)
    pps = int(result("pps"), 16)
    assert state[0] == round_id and len(state) == 5
    assert pps == int(result("pps-current"), 16) and pps > 1
    eligible = supply - state[4]
    params = decode(result("asset"))
    assert params[:3] == [int(ident == 6161), decimals, int(collateral, 16)]
    block_info = result("block")
    assert block_info["hash"] == event["blockHash"]
    timestamp = int(block_info["timestamp"], 16)
    price = evidence.eth_usdt(timestamp)
    return {
        "id": ident,
        "market": market,
        "vault": addr,
        "transaction": event["transactionHash"],
        "block": block,
        "timestamp": timestamp,
        "round": round_id,
        "net_pps": pps,
        "performance_fee": decode(event["data"])[0],
        "vault_fee": total_fee,
        "preblock_eligible_supply": eligible,
        "decimals": decimals,
        "eth_usdt": price,
        "roll_gas_price_wei": int(receipt["effectiveGasPrice"], 16),
    }


def ribbon_replays(evidence):
    groups = defaultdict(list)
    for file in sorted(evidence.path.glob("ribbon-fees-*.json")):
        for item in evidence.result(file.name):
            assert item["topics"][0] == RIBBON_FEE and not item.get("removed")
            groups[item["address"]].append(ribbon_receipt(evidence, item))
    assert set(groups) == set(VAULTS)
    results = []
    for address, observations in groups.items():
        observations.sort(key=lambda row: row["block"])
        assert len(observations) == 5
        values = []
        for opened, closed in pairwise(observations):
            assert closed["round"] == opened["round"] + 1
            assert closed["block"] > opened["block"]
            gas = sum(
                units * row["roll_gas_price_wei"] * row["eth_usdt"] / GWEI_SCALE
                for units, row in zip(RIBBON_GAS, (opened, closed), strict=True)
            )
            pnl = ribbon_return(
                starting_pps=opened["net_pps"],
                ending_pps=closed["net_pps"],
                vault_fee=closed["vault_fee"],
                eligible_shares=closed["preblock_eligible_supply"],
                decimals=closed["decimals"],
                investment=VAULT_NOTIONAL,
                investor_gas=gas,
            )
            closed["representative_investor_gas_usdt"] = gas
            closed["carry_pnl_usdt"] = pnl
            values.append((closed["timestamp"], *pnl))
        ident, market, *_ = VAULTS[address]
        results.append(
            {
                "id": ident,
                "period": "2023-07-28 through 2023-08-25",
                "group": "Ribbon · archived Theta Vault carry",
                "exit": "Consecutive on-chain settled vault rounds",
                "market": market,
                "currency": "USDT",
                "interval": "Weekly finalized PPS",
                "archive_interval": "Ethereum vault roll events and archived state",
                "order_family": "Fixed-capital single-epoch share exposure",
                **metrics(values),
            }
        )
    return results, dict(groups)


def liquity_replays(evidence):
    first_event = {}
    for file in sorted(evidence.path.glob("liquity-events-*.json")):
        for event in evidence.result(file.name):
            if event["topics"] != [REDEMPTION]:
                continue
            assert event["address"] == TROVE and not event.get("removed")
            block = int(event["blockNumber"], 16)
            if block not in first_event or int(event["logIndex"], 16) < int(
                first_event[block]["logIndex"], 16
            ):
                first_event[block] = event
    scenarios = []
    for item in [first_event[key] for key in sorted(first_event)][::5]:
        tx = item["transactionHash"]
        attempted, actual, eth, fee = decode(item["data"])
        assert 0 < REDEMPTION_SIZE <= actual <= attempted and 0 < fee < eth

        def result(label, tx=tx):
            return evidence.result(f"liquity-states/{tx}-{label}.json")

        receipt = result("receipt")
        verify_log(item, receipt)
        info = result("block")
        assert info["hash"] == item["blockHash"]
        timestamp = int(info["timestamp"], 16)
        entry, net_exit, gross_exit, gas_mark = [
            int(result(label), 16) / 10**6
            for label in ("buy", "sell", "sell-gross", "gas-mark")
        ]
        assert 0 < entry < REDEMPTION_SIZE / 10**18
        gas_price = int(receipt["effectiveGasPrice"], 16)
        gas_units = 2 * ROUTER_GAS + int(receipt["gasUsed"], 16)
        gas = gas_mark * 100 * gas_price * gas_units / GWEI_SCALE
        pnl = redemption_return(entry, gross_exit, net_exit, V3_FEE_PPM, gas)
        scenarios.append(
            {
                "transaction": tx,
                "block": int(item["blockNumber"], 16),
                "timestamp": timestamp,
                "actual_lusd": actual,
                "total_eth_before_redemption_fee": eth,
                "redemption_fee_eth": fee,
                "eligible_eth_before_fee": eth * REDEMPTION_SIZE // actual,
                "eligible_eth_after_fee": (eth - fee) * REDEMPTION_SIZE // actual,
                "entry_usdc_archive_quote": entry,
                "gross_exit_usdc_archive_quote": gross_exit,
                "net_exit_usdc_archive_quote": net_exit,
                "gas_usdc": gas,
                "gas_units": gas_units,
                "effective_gas_price_wei": gas_price,
                "pnl": pnl,
            }
        )
    assert len(scenarios) == 14
    return {
        "id": 6159,
        "period": "2023 Ethereum redemption sample",
        "group": "Liquity · historical quote redemption scenario",
        "exit": "Observed redemption rate and post-block WETH quote",
        "market": "LUSD → ETH (USDC)",
        "currency": "USDC",
        "interval": "Ethereum blocks",
        "archive_interval": "Redemption events plus historical Uniswap v3 quoting",
        "order_family": "Fixed 1,000 LUSD event-matched scenario",
        **metrics([(row["timestamp"], *row["pnl"]) for row in scenarios]),
    }, scenarios


def stability_replays(evidence):
    all_events = []
    for file in sorted(evidence.path.glob("liquity-offset-events-*.json")):
        all_events.extend(evidence.result(file.name))
    assert len(all_events) == 13
    lot = REDEMPTION_SIZE
    pool_int = int(STABILITY_POOL, 16)
    pool_topic = f"0x{pool_int:064x}"
    zero = f"0x{0:064x}"
    gas_units = 3 * ROUTER_GAS + SP_DEPOSIT_ABSOLUTE_GAS + SP_WITHDRAW_ABSOLUTE_GAS
    scenarios = []
    for event in sorted(all_events, key=lambda x: int(x["blockNumber"], 16)):
        tx = event["transactionHash"]

        def result(label, tx=tx):
            return evidence.result(f"liquity-offset/{tx}-{label}.json")

        receipt = result("receipt")
        verify_log(event, receipt)
        info = result("block")
        assert info["hash"] == event["blockHash"]
        timestamp = int(info["timestamp"], 16)
        logs = receipt["logs"]
        [burn] = [
            int(row["data"], 16)
            for row in logs
            if row["address"] == LUSD and row["topics"] == [TRANSFER, pool_topic, zero]
        ]
        [received] = [
            decode(row["data"])[1]
            for row in logs
            if row["address"] == ACTIVE_POOL
            and row["topics"] == [ETHER_SENT]
            and decode(row["data"])[0] == pool_int
        ]
        [after] = [
            int(row["data"], 16)
            for row in logs
            if row["address"] == STABILITY_POOL and row["topics"] == [LUSD_UPDATE]
        ]
        before = int(result("pre-deposits"), 16)
        assert before == after + burn
        remaining, gain = liquidation_lot(
            lusd_lot=lot,
            deposited_before=before,
            burned_lusd=burn,
            collateral_eth=received,
        )
        buy, sell_stable, sell_eth, gas_mark = [
            int(result(label), 16) / 10**6
            for label in ("buy-500", "sell-lusd-500", "sell-eth-500", "gas-mark-500")
        ]
        gas_price = int(receipt["effectiveGasPrice"], 16)
        gas = gas_mark * 100 * gas_price * gas_units / GWEI_SCALE
        pnl = redemption_return(
            buy, sell_stable + sell_eth, sell_stable + sell_eth, V3_FEE_PPM, gas
        )
        scenarios.append(
            {
                "transaction": tx,
                "block": int(event["blockNumber"], 16),
                "timestamp": timestamp,
                "pool_pre_lusd": before,
                "actual_lusd_offset": burn,
                "actual_eth_to_stability_pool": received,
                "scenario_lusd_remaining": remaining,
                "scenario_eth_acquired": gain,
                "entry_usdc_archive_quote": buy,
                "stable_exit_usdc_archive_quote": sell_stable,
                "eth_exit_usdc_archive_quote": sell_eth,
                "gas_usdc": gas,
                "gas_units": gas_units,
                "effective_gas_price_wei": gas_price,
                "pnl": pnl,
            }
        )
    return {
        "id": 6158,
        "period": "2022-11 Liquity V1 offset observations",
        "group": "Liquity · historical Stability Pool offset scenario",
        "exit": "Observed pro-rata offset and post-block WETH/LUSD quotes",
        "market": "Stability Pool ETH collateral (USDC)",
        "currency": "USDC",
        "interval": "Ethereum blocks",
        "archive_interval": "On-chain receipt and prior-block Stability Pool state",
        "order_family": "Fixed 1,000 LUSD pro-rata deposited slice",
        **metrics([(row["timestamp"], *row["pnl"]) for row in scenarios]),
    }, scenarios


def replay(path):
    evidence = Evidence(path)
    ribbon, vaults = ribbon_replays(evidence)
    liquity, redemptions = liquity_replays(evidence)
    stability, offsets = stability_replays(evidence)
    return {
        "coverage": [
            [
                6158,
                "Tested · Liquity Stability Pool offset variant",
                (
                    "13 on-chain collateral/debt offsets, tied to Stability Pool deposit state, exact LUSD "
                    "burn and Active Pool ETH transfers. A representative 1,000-LUSD deposited slice "
                    "receives pro-rata ETH. Historical exact-size USDC entry and exit quotes plus modeled gas. "
                    "Independent event scenarios exclude LQTY incentives."
                ),
            ],
            [
                6159,
                "Tested · Liquity redemption quote variant",
                (
                    "14 discounted 1,000-LUSD scenarios at observed Ethereum redemption events. "
                    "Size-matched archived Uniswap stable-entry and ETH-exit quotes, actual proportional "
                    "redemption fee, observed redemption gas and modeled router gas in USDC. "
                    "Event-matched research scenarios preserve actual large redemption fee rates."
                ),
            ],
            [
                6160,
                "Tested · Ribbon vault carry",
                (
                    "Four consecutive finalized rollover changes each for WETH and WBTC call vaults. "
                    "Archive price per share and vault fee events reconcile to receipts. "
                    "Entry-price-neutral carry excludes directional collateral returns and adds modeled investor gas."
                ),
            ],
            [
                6161,
                "Tested · Ribbon vault carry",
                (
                    "Four consecutive finalized rollover changes for the USDC-denominated ETH put vault. "
                    "Archive price per share and vault fee events reconcile to receipts. "
                    "Includes underlying vault carry and vault fee, with modeled investor gas."
                ),
            ],
        ],
        "results": [stability, liquity, *ribbon],
        "ledger": {
            "ribbon": vaults,
            "liquity_redemption": redemptions,
            "liquity_pool_offsets": offsets,
        },
        "evidence_sha256": dict(sorted(evidence.samples.items())),
        "settings": {
            "archive_state": "https://eth.drpc.org",
            "event_receipt_source": "https://ethereum.public.blockpi.network/v1/rpc/public",
            "ribbon_gas_units": RIBBON_GAS,
            "ribbon_capital_usdt": VAULT_NOTIONAL,
            "ribbon_reference": "https://github.com/ribbon-finance/ribbon-v2/blob/master/contracts/libraries/VaultLifecycle.sol",
            "ribbon_deployments": "https://github.com/ribbon-finance/ribbon-docs/blob/master/developers/contract-addresses.md",
            "ribbon_collateral_valuation": "Starting collateral value held constant for each independent epoch; USDC stable unit proxy",
            "ribbon_gas_mark": "Previous completed Binance ETHUSDT minute and archived roll effective gas price",
            "ribbon_gross_fee_addback": "Observed closing-round vault fee divided by pre-block eligible shares",
            "uniswap_router_gas_units_per_leg": ROUTER_GAS,
            "uniswap_fee_ppm": V3_FEE_PPM,
            "uniswap_reference": "https://docs.uniswap.org/contracts/v3/reference/periphery/interfaces/IQuoter",
            "liquity_reference": "https://docs.liquity.org/liquity-v1/faq/lusd-redemptions",
            "liquity_sample": "Every fifth distinct redemption block in sampled window, at first redemption log in block",
            "liquity_replay_timing": "Buy quote at B-1, observed rate from the liquidity event at B, sell quote at B.",
            "liquity_quote_fees": "Gross reverses nominal pool fees approximately; actual historical size-specific quoted cashflow reconciles after fees.",
            "stability_pool_reference": "https://docs.liquity.org/liquity-v1/faq/stability-pool-and-liquidations",
            "stability_pool_own_gas_units": [
                SP_DEPOSIT_ABSOLUTE_GAS,
                SP_WITHDRAW_ABSOLUTE_GAS,
            ],
            "stability_pool_timing": "Provisioned before the historically observed event with modeled B-1 purchase and B unwind. Not a liquidation forecasting signal.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    opts = parser.parse_args()
    report = replay(opts.input)
    opts.output.write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for row in report["results"]:
        print(row["id"], row["trades"], row["gross"], row["net"])


if __name__ == "__main__":
    main()
