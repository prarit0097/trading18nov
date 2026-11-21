"""Verify BTC/ETH scope against the pinned FMZ source archive."""

import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

CASES = (
    (
        391,
        "d8fcf56fdb4ef614d9dd63e6eac2623d00d08be8a038f199233f8108b5b4840f",
        (
            "LTC_BTC",
            "|min|0.0085|",
            "|max|0.008534|",
            "exchange.Sell(-1, 1)",
            "exchange.Buy(-1, 1)",
        ),
        "Excluded · original LTC/BTC threshold strategy",
        "Saved Huobi configuration trades one LTC per order at fixed BTC-per-LTC thresholds. BTC is the quote unit. A BTC or ETH base-asset result would require new instrument settings and thresholds.",
        ("https://www.fmz.com/strategy/113871",),
    ),
    (
        405,
        "2c59af991f9a7acc2ffee9d6c90326a03ecb4f5d2262a17b20fd0f0b6f5b3817",
        ("HUSD/USDT", "回归1", "|MAX_ATR|0.0001|", "getLastATR() <= _config.maxATR"),
        "Excluded · original HUSD/USDT peg arbitrage",
        "The author targets a zero-fee Huobi HUSD campaign and a stablecoin price returning to 1. BTC/ETH candles do not represent that peg or fee regime.",
        ("https://www.fmz.com/strategy/164047",),
    ),
    (
        1017,
        "5578b74abf4694fb669d15bf34443d1a09c2466d45ece9bbaf3df4509b3e9640",
        (
            'dictParam["type"] == "buy"',
            'float(dictParam["amount"])',
            "ThreadingHTTPServer(host, Executor)",
            "Sleep(2000)",
        ),
        "Excluded · external TradingView order relay",
        "Order side and quantity are taken from incoming webhook commands. Its main loop publishes status and does not generate market signals. The archive supplies the executor without a historical signal generator.",
        ("https://www.fmz.com/strategy/221850",),
    ),
    (
        1021,
        "c100b6e087db5c6c87a48c46b7f830cf6c11dc24477a75251c6cbe50d6e53615",
        (
            'task.Action = signal["Action"]',
            "tradeFunc(task.Price, task.Amount)",
            'objSignal["Flag"] == "TestSignal"',
            "manager.newTask(objSignal)",
        ),
        "Excluded · external HTTP signal executor",
        "Market depth supplies execution precision. Incoming messages supply action, market, price and quantity. The sample BTC template documents the payload format and supplies no historical decision rules.",
        (
            "https://www.fmz.com/strategy/475235",
            "https://www.fmz.com/digest-topic/10556",
        ),
    ),
    (
        1384,
        "b53c9680909c6640b0af00566160eec148e90d8a25b285b33d0b8ea506bbcf13",
        (
            "2021/11/4冲DAR开盘",
            "|XX|200|",
            "exchange.GetCurrency()",
            "if ticker:",
            "Sleep(15*1000)",
        ),
        "Pending · original new-listing timestamp and fills",
        "Recovered XX=200. The documented deployment was the Binance DAR listing on 4 November 2021 at 08:00 UTC, with four possible quote pairs. Source can use a configured market. A comparable BTC/ETH case needs a provable first tradable ticker and the first-second execution inputs expected by the original strategy.",
        (
            "https://www.fmz.com/strategy/324178",
            "https://www.binance.com/en/support/announcement/detail/28c68286fe9340cd97740774b4e13af9",
        ),
    ),
    (
        1392,
        "c774ac031a74d9366f17845b1410ddd2a8f97f93937ec06671edd3252a65ae57",
        (
            "symbol = 'huobip/ht_usdt'",
            "max_price = 1.5",
            "min_price = 0.5",
            "exchange.SetContractType(symbol)",
            "if buy_price <= max_price and sell_price >= min_price:",
        ),
        "Excluded · fixed Huobi Token market",
        "The only configured instrument is HT/USDT. Entry uses fixed HT price bounds of 0.5 and 1.5. Replacing the market and bounds would create a different setup.",
        ("https://www.fmz.com/strategy/410113",),
    ),
)


def main(archive_path, prior_path, output_path):
    prior = json.loads(prior_path.read_bytes())
    pending = {
        row["id"]: row["source"]
        for row in prior["disposition"]
        if not row["status"].startswith(("Tested", "Excluded"))
    }
    coverage = []
    evidence = []
    with ZipFile(archive_path) as archive:
        for identifier, digest, markers, status, reason, references in CASES:
            source = pending[identifier]
            revision, filename = unquote(source.split("/blob/", 1)[1]).split("/", 1)
            raw = archive.read(f"strategies-{revision}/{filename}")
            assert hashlib.sha256(raw).hexdigest() == digest, identifier
            lines = raw.decode("utf-8-sig").splitlines()
            verified_lines = []
            for marker in markers:
                matches = [
                    number for number, line in enumerate(lines, 1) if marker in line
                ]
                assert matches, (identifier, marker)
                verified_lines.extend(matches)
            coverage.append([identifier, status, reason])
            evidence.append(
                {
                    "id": identifier,
                    "source": source,
                    "source_sha256": digest,
                    "reviewed_source_lines": sorted(set(verified_lines)),
                    "public_references": references,
                }
            )
    output = {
        "schema": "Pinned FMZ strategy scope and eligibility review",
        "prior_checkpoint_sha256": hashlib.sha256(prior_path.read_bytes()).hexdigest(),
        "evidence": evidence,
        "coverage": coverage,
        "results": [],
    }
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
