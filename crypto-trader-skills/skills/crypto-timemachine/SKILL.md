---
name: crypto-timemachine
description: Use when the user needs seeded crypto entry-stop-target scenario replay or loss-tail stress testing.
---

# Crypto Time Machine

Resample contiguous historical OHLC return blocks. Compare settled net PnL, cost-adjusted wins and tail loss separately from underlying price returns. Always report historical pool size and distinct blocks; 10000 paths do not create 10000 independent observations.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-timemachine/scripts/timemachine.py --workspace ./my-demo --replays 10000 --steps 20 --block-size 4 --seed 19 --now 2026-11-17T12:00:00Z
```

CLI command: `simulate`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: config, validated market history and current plan.

Writes: simulation, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

Spot long, per-unit scenario outcomes only. No position sizing, margin, liquidation, funding or calibrated probabilities.
