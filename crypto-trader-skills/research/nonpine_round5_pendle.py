"""Pendle fixed-carry replay from public Ethereum BUY_PT swap receipts."""

import argparse
import csv
import hashlib
import json
import math
import re
import zipfile
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path

from .nonpine_round4_metrics import metrics

SWAP = "0x829000a5bc6a12d46e30cdcecd7c56b1efd88f6d7d059da6734a04f3764557c4"
INTEREST_INDEX = "0x71475f2f645813fdbebf53a58968008bff11ee21a58f01c5a9cc263d0bc4703d"
API = "https://api-v2.pendle.finance/core"
REDEMPTION_GAS_UNITS = 200_000
MARKETS = {
    "BTC": ("LBTC", "WBTC", "0xefa9339980ffee3304af4822b80484bfcc6f35ee", 10**8, 400),
    "ETH": (
        "wstETH",
        "stETH",
        "0xba1cbaece600beec76dabc0a4ead31e0339cbe37",
        10**18,
        300,
    ),
}


def event_logs(receipt, address, topic):
    return [
        entry
        for entry in receipt["logs"]
        if entry["address"].lower() == address and entry["topics"][:1] == [topic]
    ]


def market_swap(receipt, market, yield_token, scale, reported_pt):
    events = event_logs(receipt, market, SWAP)
    if receipt["status"] != "0x1" or len(events) != 1:
        return None
    event = events[0]
    data = bytes.fromhex(event["data"][2:])
    if len(data) != 128 or len(event["topics"]) != 3:
        return None
    pt, sy, fee, reserve = [
        int.from_bytes(data[offset : offset + 32], "big", signed=offset < 64)
        for offset in range(0, 128, 32)
    ]
    if not (pt > 0 and sy < 0 and 0 <= reserve <= fee < -sy):
        return None
    if not math.isclose(pt / scale, reported_pt, rel_tol=1e-12, abs_tol=0):
        return None
    swap_index = int(event["logIndex"], 16)
    preceding = {
        int(item["logIndex"], 16): int(item["topics"][1], 16)
        for item in event_logs(receipt, yield_token, INTEREST_INDEX)
        if len(item["topics"]) == 2
        and item["data"] == "0x"
        and int(item["logIndex"], 16) < swap_index
    }
    if not preceding:
        return None
    index = preceding[max(preceding)]
    return (pt, -sy, fee, index) if index > 0 else None


def cashflows(swap, scale, asset_price, eth_price, gas_used, gas_price):
    pt, sy_in, fee, index = swap
    unit = 10**18 * scale
    entry = sy_in * index / unit * asset_price
    swap_fee = fee * index / unit * asset_price
    gross = pt / scale * asset_price - entry + swap_fee
    gas_unit_price = gas_price / 10**18 * eth_price
    return (
        gross,
        swap_fee,
        gas_used * gas_unit_price,
        REDEMPTION_GAS_UNITS * gas_unit_price,
        entry,
    )


def unix_ms(value):
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def spot_close(path):
    with zipfile.ZipFile(path) as archive:
        (name,) = archive.namelist()
        with archive.open(name) as content:
            return {
                opened // (1000 if opened >= 10**15 else 1): float(row[4])
                for row in csv.reader(TextIOWrapper(content, encoding="utf-8"))
                if (opened := int(row[0]))
            }


def read_input(path, source, evidence):
    raw = path.read_bytes()
    evidence[source] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def replay_market(base, coin, evidence):
    label, accounting_asset, market, scale, page = MARKETS[coin]
    addresses = read_input(
        base / f"pendle-{page}.json",
        f"{API}/v2/markets/all?limit=100&skip={page}",
        evidence,
    )
    metadata = next(row for row in addresses["results"] if row["address"] == market)
    assert metadata["chainId"] == 1 and metadata["name"] == label
    yield_token = metadata["yt"].split("-", 1)[1].lower()
    pool_history = read_input(
        base / f"pt{coin.lower()}-buy.json",
        f"{API}/v5/1/transactions/{market}?action=BUY_PT&limit=100",
        evidence,
    )
    maturity = unix_ms(metadata["expiry"])
    prices = {}
    snapshots = []
    seen = set()
    for row in sorted(
        pool_history["results"], key=lambda item: item["timestamp"], reverse=True
    ):
        if len(snapshots) == 5:
            break
        if not row["isClearAction"] or not 25 <= row["value"] <= 1500:
            continue
        tx = row["txHash"]
        opened = unix_ms(row["timestamp"])
        assert (
            re.fullmatch("0x[0-9a-f]{64}", tx)
            and row["action"] == "BUY_PT"
            and row["chainId"] == 1
            and row["market"] == f"1-{market}"
            and opened < maturity
        )
        if tx in seen:
            continue
        seen.add(tx)
        path = base / "pt-receipts" / f"{tx}.json"
        if not path.is_file():
            continue
        receipt = read_input(
            path, f"ethereum:eth_getTransactionReceipt:{tx}", evidence
        )["result"]
        assert receipt["transactionHash"] == tx
        swap = market_swap(receipt, market, yield_token, scale, row["notional"]["pt"])
        if swap is None:
            continue
        valuation = []
        for asset in (coin, "ETH"):
            month = row["timestamp"][:7]
            key = f"{asset}USDT-1m-{month}.zip"
            if key not in prices:
                spot_file = base / "pt-spot" / key
                url = f"https://data.binance.vision/data/spot/monthly/klines/{asset}USDT/1m/{key}"
                evidence[url] = hashlib.sha256(spot_file.read_bytes()).hexdigest()
                prices[key] = spot_close(spot_file)
            value = prices[key][opened // 60_000 * 60_000 - 60_000]
            assert math.isfinite(value) and value > 0
            valuation.append(value)
        gas_used = int(receipt["gasUsed"], 16)
        gas_price = int(receipt["effectiveGasPrice"], 16)
        assert gas_used >= 21_000 and gas_price > 0
        gross, swap_fee, purchase_gas, redemption_gas, entry = cashflows(
            swap, scale, *valuation, gas_used, gas_price
        )
        snapshots.append(
            {
                "tx": tx,
                "opened": row["timestamp"],
                "maturity": metadata["expiry"],
                "pt_raw": swap[0],
                "sy_input_raw": swap[1],
                "sy_fee_raw": swap[2],
                "py_index": swap[3],
                "asset_usdt": valuation[0],
                "eth_usdt": valuation[1],
                "gas_used": gas_used,
                "effective_gas_price_wei": gas_price,
                "entry_conversion_usdt": entry,
                "gross": gross,
                "swap_fee": swap_fee,
                "purchase_gas": purchase_gas,
                "redemption_gas_model": redemption_gas,
            }
        )
    assert len(snapshots) == 5
    assert (
        sum(item["entry_conversion_usdt"] + item["purchase_gas"] for item in snapshots)
        < 10_000
    )
    settlements = [
        (
            maturity,
            item["gross"],
            item["swap_fee"] + item["purchase_gas"] + item["redemption_gas_model"],
            0,
        )
        for item in snapshots
    ]
    result = {
        "id": 6147,
        "period": f"{snapshots[-1]['opened'][:10]} through {metadata['expiry'][:10]}",
        "group": "Pendle · PT fixed-carry variant",
        "exit": "Modeled 1:1 at maturity",
        "market": f"{coin} PT-{label} ({accounting_asset})",
        "currency": "USDT",
        "interval": "On-chain swaps",
        "archive_interval": "Receipt plus 1m valuation proxy",
        "order_family": "Observed PT purchase; modeled redemption",
        **metrics(settlements),
    }
    return result, {"market": market, "candidates": len(seen), "samples": snapshots}


def replay(base):
    evidence = {}
    executed = {coin: replay_market(base, coin, evidence) for coin in MARKETS}
    return {
        "coverage": [
            [
                6147,
                "Tested · Pendle PT fixed-carry variant",
                (
                    "LBTC and wstETH single-market buys reconciled with Ethereum Swap logs. "
                    "Modeled maturity at par in the accounting asset. Entry-spot USDT proxy "
                    "isolates carry. Includes pool fee, observed purchase gas and modeled redemption gas. "
                    "Drawdown uses realized maturity batches."
                ),
            ],
            [
                6148,
                "Protocol history and rules needed",
                (
                    "PT buy receipts cannot reconstruct YT interest, reward accrual and collection, "
                    "or YT entry execution through maturity."
                ),
            ],
            [
                6149,
                "Protocol history and rules needed",
                (
                    "Requires actual LP mint and burn flows, pool share accounting, incentive rewards "
                    "and share valuation at each modeled exit."
                ),
            ],
            [
                6150,
                "Protocol history and rules needed",
                (
                    "Requires matched SY tokenization, retained PT accounting, YT sale execution "
                    "and both gas paths for the same historical window."
                ),
            ],
            [
                6151,
                "Protocol history and rules needed",
                (
                    "Requires simultaneous executable PT, YT and SY quotes with sufficient size and "
                    "gas/fees for both directions. Single-leg trade receipts do not establish parity."
                ),
            ],
        ],
        "results": [result for result, _ in executed.values()],
        "evidence": evidence,
        "ledger": {coin: ledger for coin, (_, ledger) in executed.items()},
        "settings": {
            "initial_equity_usdt": 10_000,
            "samples_per_market": 5,
            "receipt_source": "https://ethereum.public.blockpi.network/v1/rpc/public",
            "pt_redemption_reference": "https://docs.pendle.finance/pendle-v2/ProtocolMechanics/YieldTokenization/PT",
            "swap_abi_reference": "https://github.com/pendle-finance/pendle-core-v2-public/blob/main/contracts/interfaces/IPMarket.sol",
            "fee_accounting_reference": "https://github.com/pendle-finance/pendle-core-v2-public/blob/main/contracts/core/Market/MarketMathCore.sol",
            "redemption_gas_units": REDEMPTION_GAS_UNITS,
            "redemption_gas_price": "Each entry receipt's effective gas price; modeled",
            "redemption_ratio": "1 accounting unit per PT; assumes no underlying impairment",
            "valuation": "Previous completed Binance BTCUSDT/ETHUSDT minute at entry; excludes spot beta and wrapper basis",
            "fees": "Pool fee plus actual purchase gas and model redemption gas",
            "excluded": "External route fees and any extra swap between SY and accounting token",
            "entry_selection": "Five most recent reconciled eligible purchases per market in archived first API results page",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = replay(args.input)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for row in report["results"]:
        print(
            row["market"], row["trades"], row["gross"], row["after_fees"], row["net_dd"]
        )


if __name__ == "__main__":
    main()
