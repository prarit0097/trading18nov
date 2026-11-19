---
name: crypto-backtest
description: Use when the user needs an offline historical crypto breakout backtest with explicit fill assumptions.
---

# Crypto Backtest

Inspect trade_count, fees, net_pnl, drawdown, assumptions and limits. Signals use lagged closed bars and next-bar open fills. Stop wins unknown intrabar stop/target ordering, gaps can worsen loss. This is a baseline research engine, not full strategy qualification.

## Run

Installed bundle root: `E:\coding\code\Trade\crypto-trader-skills`. Run from that directory with Python 3.11 or later. The configured local interpreter is `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`. All skill folders must remain beside the shared `crypto_skills` runtime. Use the same explicit workspace on every command.

```powershell
python skills/crypto-backtest/scripts/backtest.py --workspace ./my-demo --now 2026-11-17T12:00:00Z
```

CLI command: `backtest`. Use `--help` for options. `--now` overrides time for historical/offline tests; omit it for current reads. Fixture commands require a workspace initialized using the fictional example config.

## JSON handoff

Reads: config and validated market history.

Writes: backtest, under `<workspace>/trader/`. Read the resulting envelope and `data`, not terminal prose. Check status, reasons, provenance and input digests before the next stage. A blocked, waiting, stale or invalid result must never be described as a ready trade.

[Artifact contract and stage graph](E:/coding/code/Trade/crypto-trader-skills/references/artifacts.md) · [Setup and scope](E:/coding/code/Trade/crypto-trader-skills/README.md)

## Boundaries

Spot long only. No funding, liquidation, borrow, order-book queue, partial fills or market impact. No automated walk-forward, purged validation or parameter search. Do not promote from one profitable run.

## Performance evidence

For strategy improvement, use the chronological validation tool before treating a backtest as evidence. A rejected qualification must remain rejected; inspect costs, trade count and unseen-period lineage. Paper and historical long plans now share signal-close stop/target arithmetic.

[Validation commands and evidence](E:/coding/code/Trade/crypto-trader-skills/references/validation.md)
