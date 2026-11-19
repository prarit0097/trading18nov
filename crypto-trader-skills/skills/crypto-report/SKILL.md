---
name: crypto-report
description: Use when the user needs to inspect shared crypto skill results, provenance, changed inputs or a candle-volume chart.
---

# Crypto Report

Inspect upstream errors and changed_inputs; do not turn inspection into order approval. Chart shows observed candle prices and base volume only. Missing or invalid artifacts must be reported, and synthetic data must be labeled.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-report/scripts/report.py --workspace ./my-demo --now 2026-11-17T12:00:00Z
```

CLI command: `report or status`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: all available artifacts.

Writes: report.json under `<workspace>/trader/` and chart.svg at `<workspace>/chart.svg`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

Paper research only. No paid feed, real orders, exchange keys or guarantee of profit. Spot and perpetual capabilities differ; read the scope table before claiming support.

## Performance evidence

When qualification.json is present, report its status, chosen configuration, held-out metrics, doubled costs and uncertainty separately from execution risk. A rejected result is not a trading recommendation. Report independent research accounts separately from the shared paper ledger.

[Validation commands and evidence](E:/coding/code/Trade/crypto-trader-skills/references/validation.md)

## Paper exit monitoring

Include watcher status, finished time, source errors and actual closed order IDs. Its recent PnL estimates include modeled costs and are observation-time marks. Do not imply permanent monitoring or reconstruct a touch before startup.

[Bounded watcher](E:/coding/code/Trade/crypto-trader-skills/PAPER-EXIT-DESIGN.md)
