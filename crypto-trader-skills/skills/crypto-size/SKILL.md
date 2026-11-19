---
name: crypto-size
description: Use when the user needs crypto paper position quantity from explicit cash, costs and risk limits.
---

# Crypto Size

Require explicit risk_budget, max_notional, max_total_exposure and max_daily_loss. Use Decimal arithmetic and matching exchange steps, ticks and minimum notional. Report estimated worst_case_loss with its gap-free stop assumption.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-size/scripts/size.py --workspace ./my-demo --now 2026-11-17T12:00:00Z
```

CLI command: `size`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: config, market, proposal, plan and authoritative paper account.

Writes: sizing; initial ledger, portfolio and orders if absent, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

Paper research only. No paid feed, real orders, exchange keys or guarantee of profit. Spot and perpetual capabilities differ; read the scope table before claiming support.
