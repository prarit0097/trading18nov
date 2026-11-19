---
name: crypto-exit
description: Use when the user needs an entry-linked crypto stop and target plan before position sizing.
---

# Crypto Exit

Require a current ready proposal. Inspect entry, stop, target, side and assumptions. The percentage stop and R-multiple target are transparent research rules; protective exit execution is not automatic.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-exit/scripts/exit.py --workspace ./my-demo --now 2026-11-17T12:00:00Z
```

CLI command: `plan`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: config, market and proposal.

Writes: plan, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

Paper research only. No paid feed, real orders, exchange keys or guarantee of profit. Spot and perpetual capabilities differ; read the scope table before claiming support.

## Paper exit monitoring

Protective paper exits can be checked with an explicitly running bounded paper watch. Existing levels trigger on observed bid, with adverse fill/fees; no protective order exists at the exchange and no watch starts implicitly.

[Bounded watcher](E:/coding/code/Trade/crypto-trader-skills/PAPER-EXIT-DESIGN.md)
