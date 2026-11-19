---
name: crypto-workflow
description: Use when the user wants to run or inspect the connected crypto research and paper-trading workflow.
---

# Crypto Workflow

Read config and status first. Ask for missing personal risk limits; never infer them from demo limits. Run individual stages or pipeline, inspect JSON, then run paper submit only when requested. The pipeline never submits an order.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python run.py demo --workspace ./my-demo
```

CLI command: `init, pipeline, demo or status`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: config plus the stage-specific JSON.

Writes: config and downstream stage artifacts, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

Paper research only. No paid feed, real orders, exchange keys or guarantee of profit. Spot and perpetual capabilities differ; read the scope table before claiming support.

## Performance evidence

Before presenting a rule change as an improvement, inspect its research qualification. Current baseline and the first candidate pilot are unqualified. Explicit manual paper requests are execution tests; preserve their provenance and exclude them from strategy performance. A research pass never authorizes real orders.

[Validation commands and evidence](E:/coding/code/Trade/crypto-trader-skills/references/validation.md)

## Paper exit monitoring

For open Binance spot paper positions, the explicit paper watch command performs bounded automatic stop/target checks. Treat watcher.running=false as stopped and disclose any source errors. Starting a position does not start a watcher.

[Bounded watcher](E:/coding/code/Trade/crypto-trader-skills/PAPER-EXIT-DESIGN.md)
