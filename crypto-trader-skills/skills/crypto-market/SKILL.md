---
name: crypto-market
description: Use when the user needs BTC or ETH OHLCV, bid/ask, exchange filters or market-data health.
---

# Crypto Market

Import exactly declared units and closed contiguous bars. A failed refresh invalidates the prior market. Inspect health.valid and source before downstream use. Public fetching supports Binance spot only.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-market/scripts/market.py --workspace ./my-demo --input examples/market.json --now 2026-11-17T12:00:00Z
```

CLI command: `market`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: config and a plain market import or explicit public REST reads.

Writes: market, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

Snapshot REST only; no persistent WebSocket, order-book sequence replay or exchange clock synchronization. Limit 1000 bars per ingest. Freshness thresholds are configurable and are not a latency SLA.
