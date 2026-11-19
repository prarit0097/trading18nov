---
name: crypto-risk
description: Use when the user needs to validate freshness, lineage, cash or exposure before a crypto paper order.
---

# Crypto Risk

Require approved=true, a valid expires_at, unchanged input digests and account. Rebuild downstream stages after any upstream change. Paper submit rechecks under a lock. JSON hashes detect changed content; they are not signatures or permissions.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-risk/scripts/risk.py --workspace ./my-demo --now 2026-11-17T12:00:00Z
```

CLI command: `risk`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: config, market, proposal, plan, sizing and paper account.

Writes: risk, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

Paper research only. No paid feed, real orders, exchange keys or guarantee of profit. Spot and perpetual capabilities differ; read the scope table before claiming support.

## Performance evidence

Execution risk approval checks arithmetic and current inputs; it does not establish a profitable strategy. Treat research qualification separately. Do not present a manual override or WAIT-to-manual entry as a model signal.

[Validation commands and evidence](E:/coding/code/Trade/crypto-trader-skills/references/validation.md)

## Paper exit monitoring

Bounded watcher exits use fresh observed bids, existing levels and recorded per-position costs. They do not reset risk budgets or validate strategy profitability. Inspect quote freshness/errors and watcher completion; there is no continuous service after the command ends.

[Bounded watcher](E:/coding/code/Trade/crypto-trader-skills/PAPER-EXIT-DESIGN.md)
