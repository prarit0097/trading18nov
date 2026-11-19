---
name: crypto-world
description: Use when the user needs a finite-cash synthetic crypto market stress run with thousands of participants.
---

# Crypto World

Run actual lightweight participants, inspect matched volume, participant count and cash/inventory conservation. Orders match in batches at midpoint; unmatched orders expire each step. Random policies are not calibrated trader behavior. This is not MiroFish or real people.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-world/scripts/world.py --workspace ./my-demo --agents 10000 --steps 20 --seed 19 --now 2026-11-17T12:00:00Z
```

CLI command: `world`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: config and validated market history.

Writes: world, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

At most 10000 participants and 100 steps, no LLM calls or external flow. Aggregate synthetic volume is separate from actual exchange volume.
