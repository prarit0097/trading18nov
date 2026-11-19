---
name: crypto-paper
description: Use when the user requests simulated crypto orders, bounded SL/TP monitoring, hypothetical closes or paper-ledger inspection.
---

# Crypto Paper

Spot long only. Inspect approved risk before submit. Retried identical submissions do not spend cash twice. Close sells the current position; --price is an explicitly hypothetical manual mark with fees. Do not describe these as exchange orders.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-paper/scripts/paper.py submit --workspace ./my-demo --now 2026-11-17T12:00:00Z
```

CLI command: `paper submit`, `paper close` or `paper watch`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: current approved risk and its inputs for submit; ledger for close.

Writes: ledger, portfolio and orders, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

No live connector or exchange keys. Bounded paper SL/TP checking runs only while an explicit watch command is running. Perpetual execution is blocked; gaps and missed poll intervals can exceed estimated risk.

## Bounded SL/TP observation

From the installed bundle root, use the isolated interpreter:

```powershell
.\.venv\Scripts\python.exe skills/crypto-paper/scripts/paper.py watch --workspace <paper-workspace> --duration-seconds 60 --poll-seconds 15
```

Default duration0 checks once; duration may be0..3600seconds and poll5..300seconds. Do not pass --now, --price, --input, --fetch or --symbol. It checks all supported Binance spot positions. Confirm watcher.running, finished_at and source errors; monitoring ends when the command ends. Source/quote failure never authorizes a fabricated close. No missed historic touch is reconstructed. New positions snapshot their costs; legacy positions require verified per-asset entry archives.

[Exit-monitor design](E:/coding/code/Trade/crypto-trader-skills/PAPER-EXIT-DESIGN.md) · [Verified results](E:/coding/code/Trade/crypto-trader-skills/PAPER-EXIT-RESULTS.md)
