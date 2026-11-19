# Bounded paper-exit monitoring: verified results

Implemented explicit automatic paper SL/TP checks. This improves execution/risk mechanics; it does not demonstrate a profitable strategy or increased future win probability. The rejected earlier research remains rejected and its original source is frozen for replay.

## Fresh verification

- 101 regression tests pass;18 watcher-specific tests cover stop/target/no-touch, adverse gap fill, both fees/cash/daily-PnL reconciliation, stale/future/mismatched quotes, legacy snapshot validation, per-symbol cost independence, duplicate/concurrent manual closes, committed-ledger projection recovery, watcher lease, polling bounds, interruption and CLI errors.
- All12 installed skill metadata/link checks pass; compilation passes. The completed prior research result replays from its verified original frozen source.
- Independent bounded code review found no concrete must-fix issue.

## Public-data run

Ran the installed crypto-paper wrapper on the existing shared virtual BTC/ETH/SOL account for60.329seconds. Completed4cycles and12position checks, with0source errors and0new paper exits. No observed bid crossed its recorded SL/TP; no close was manufactured. All3positions remain open. This run verified real quote acquisition and no-touch handling; actual stop/target closures were covered by controlled regression fixtures, not observed in this market run.

Snapshot around2026-11-18 02:02:54IST (quotes were acquired sequentially):

| Asset | Observed bid USDT | Estimated net unrealized PnL USDT | State |
|---|---:|---:|---|
| BTCUSDT | 64037.60 | +2.74 | holding |
| ETHUSDT | 1799.92 | +3.75 | holding |
| SOLUSDT | 73.14 | +0.67 | holding |

Total estimated unrealized PnL:+7.15USDT, including assumed entry/exit fees and adverse exit slippage. Realized PnL remains0USDT. These manual execution-test positions are not evidence that the rejected strategy has an edge. Cash remained5996.07USDT. Before/after cash, inventory and order count reconcile; global configuration is unchanged. No real exchange order was sent.

## Run explicitly

```powershell
Set-Location 'E:\coding\code\Trade\crypto-trader-skills'
.\.venv\Scripts\python.exe skills/crypto-paper/scripts/paper.py watch --workspace "E:\coding\code\Trade\crypto-trader-skills\runs\manual-real-paper-btc-eth-sol-20261117T190847278192Z" --duration-seconds 60 --poll-seconds 15
```

Duration0 checks once. A bounded foreground command stops at completion; **this60-second watch has ended and no background monitoring is active**. Both watcher and writer locks were released. A stopped process cannot protect positions. Never infer that missed historic touches were watched or filled.

## Evidence

[Full real-data result](verification/paper-exits/real-data-watch-result.json) · [test output](verification/paper-exits/unit-tests.txt) · [source/check manifest](verification/paper-exits/checks.json) · [before ledger](verification/paper-exits/ledger-before.json) · [after ledger](verification/paper-exits/ledger-after.json) · [design](PAPER-EXIT-DESIGN.md) · [plan](PAPER-EXIT-PLAN.md).

The actual paper workspace stores trader/watcher.json, quote_<symbol>.json and ledger/portfolio/orders. New positions retain per-position exit-model snapshots; legacy entry archives are integrity-checked. Observed exit orders embed their triggering quote and model for audit. Public bookTicker has no exchange event timestamp: only local request/receipt freshness can be verified. Costs/ticks use entry-model assumptions; no full depth, partial fills, market impact or continuously running infrastructure is modeled. Daily loss rules remain the existing realized-loss cutoff; a rolling marked-loss kill switch was not added.
