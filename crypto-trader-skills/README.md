# Connected Crypto Trader Skills

`planv1.md` se banaya gaya executable crypto research aur **paper trading** pack. Python 3.11+, standard library only; no `pip install`, paid subscription, API key or live-order endpoint. BTC/USDT and ETH/USDT use the same contracts. The included data and risk limits are fictional examples, not recommendations.

## Quick start

PowerShell, bundle root:

```powershell
Set-Location 'E:\coding\code\Trade\crypto-trader-skills'
python run.py demo --workspace ./my-demo
python run.py status --workspace ./my-demo
python run.py report --workspace ./my-demo --now 2026-11-17T12:00:00Z
```

Use a NEW demo workspace each time. `demo` uses synthetic BTC candles/news, fictional limits, a pinned historical clock, 10,000 replays and 10,000 actual lightweight simulated participants. It submits one fictional paper order. Results live in `my-demo/trader/*.json`; open `my-demo/chart.svg` for candle and base-volume inspection. No exchange order is sent. Pinned data is not fresh market data today.

For a manual run, initialize first, then invoke each skill with the same workspace:

```powershell
python run.py init --workspace ./manual-demo --input examples/paper-config.json --now 2026-11-17T12:00:00Z
python skills/crypto-market/scripts/market.py --workspace ./manual-demo --input examples/market.json --now 2026-11-17T12:00:00Z
python skills/crypto-news/scripts/news.py --workspace ./manual-demo --input examples/news.json --now 2026-11-17T12:00:00Z
python skills/crypto-entry/scripts/entry.py --workspace ./manual-demo --now 2026-11-17T12:00:00Z
python skills/crypto-exit/scripts/exit.py --workspace ./manual-demo --now 2026-11-17T12:00:00Z
python skills/crypto-size/scripts/size.py --workspace ./manual-demo --now 2026-11-17T12:00:00Z
python skills/crypto-risk/scripts/risk.py --workspace ./manual-demo --now 2026-11-17T12:00:00Z
python skills/crypto-paper/scripts/paper.py submit --workspace ./manual-demo --now 2026-11-17T12:00:00Z
python skills/crypto-report/scripts/report.py --workspace ./manual-demo --now 2026-11-17T12:00:00Z
```

Inspect each JSON before proceeding. `python run.py pipeline --workspace ... --input ...` runs market → entry → plan → size → risk, **without** paper submission. `init` without an example leaves personal risk limits unset; configure your own limits before sizing. Existing config is preserved. To intentionally update a config, use `Workspace.write('config', data)` from the shared runtime; rebuild downstream artifacts afterward. Do not hand-edit JSON without recomputing its envelope digest.

## Skills and handoffs

| Skill | Responsibility | Shared output |
|---|---|---|
| [crypto-workflow](skills/crypto-workflow/SKILL.md) | Initialize, orchestrate, inspect | config and stage outputs |
| [crypto-market](skills/crypto-market/SKILL.md) | OHLCV, bid/ask, units, filters, health | market.json |
| [crypto-news](skills/crypto-news/SKILL.md) | RSS/Atom/import, versions, source freshness | news.json |
| [crypto-entry](skills/crypto-entry/SKILL.md) | Lagged breakout and RVOL | proposal.json |
| [crypto-exit](skills/crypto-exit/SKILL.md) | Entry, percentage stop, R-multiple target | plan.json |
| [crypto-size](skills/crypto-size/SKILL.md) | Decimal quantity, costs and limits | sizing.json |
| [crypto-risk](skills/crypto-risk/SKILL.md) | Current lineage, expiry, cash and risk gate | risk.json |
| [crypto-paper](skills/crypto-paper/SKILL.md) | Idempotent fictional buy/close, cash ledger | ledger/portfolio/orders.json |
| [crypto-backtest](skills/crypto-backtest/SKILL.md) | Closed-bar next-open historical research | backtest.json |
| [crypto-timemachine](skills/crypto-timemachine/SKILL.md) | Seeded contiguous-block scenario replay | simulation.json |
| [crypto-world](skills/crypto-world/SKILL.md) | Finite-cash synthetic-agent batch market | world.json |
| [crypto-report](skills/crypto-report/SKILL.md) | Results, provenance and observed chart | report.json, chart.svg |

This is file-based communication: Python writes typed JSON artifacts and the next skill reads them. Skills do not hold an independent chat or run as autonomous background agents. News feeds into inspection/reporting; it does not fabricate a sentiment score or modify the breakout signal. Research results are independent branches, not an automatic trading approval.

An agent with file access and a Python execution tool can read the relevant `SKILL.md` and execute its wrapper. The 12 skills are registered in the documented user discovery root `C:\Users\hp\.agents\skills` through NTFS junctions to this bundle. If discovery does not refresh, restart Codex. Earlier Codex-home links are retained for compatibility. The isolated Python interpreter is `.venv/Scripts/python.exe`. Keep the bundle at this path: installed links and local documentation refer to it. This local Codex installation does not install tools into the separate ChatGPT web/mobile app. Instructions require Python/file tools to execute. See [local installation](INSTALLATION.md).

## Current data and free news

For current Binance spot reads, create a config with `venue: binance`, the correct symbol/base/quote, and explicit current exchange filters and your own risk limits. Then:

```powershell
python run.py market --workspace ./btc-paper --fetch --symbol BTCUSDT --interval 5m --limit 100
python run.py news --workspace ./btc-paper --fetch
```

News requires 1–20 distinct public RSS/Atom URLs in config `source_urls`. No default feed is silently selected. Polling is one bounded pass per command, sequential across sources; minimum 60-second per-source interval plus server cache/Retry-After delays (each server delay capped at seven days), conditional ETag/Last-Modified requests. Network availability and publication lag depend on the source. `first_seen` is local observation time, not publication or event time. `last_seen` is not proof that an article is newly published. Items retain correction-version hashes; no automatic archival (stop at 10,000 items or 100 versions/item).

Public market reads use [Binance's market-data-only domain](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md), exchangeInfo, klines and bookTicker only. No auth/order route exists. Fetch reads are snapshots and do not promise tick-level timing. Imported filters and config must match exactly for execution. The current read-only collector does not auto-change config risk settings or venue rules.

## Plan V1 coverage and limits

| Plan requirement | Working capability | Remaining qualification |
|---|---|---|
| Fast, free crypto news | Bounded public polling/import, durable dedupe, source health | Continuous collection, push sources, alerts and latency measurements |
| Backtesting | Signal-plan parity, costs, conservative fills; bounded chronological train/validation/test pilot | Full walk-forward/purged validation, liquidity/impact/partial fills |
| History/charts/volume | Validated contiguous closed OHLCV, base-volume/RVOL, SVG candles | Historical archive/pagination, persistent WebSocket L2, trade delta/CVD |
| Time Machine | 10,000 seeded block replays of a plan, settled PnL/tails | Calibrated probabilities and real execution replay |
| MiroFish-style world | 10,000 lightweight participants, funded matching, conservation | Actual MiroFish/OASIS/Zep integration and calibrated behavior |
| Risk/entry/exit/size | Explicit limits, Decimal costs, freshness, lineage, idempotent ledger and bounded paper SL/TP watcher | Always-on operational monitoring, multi-asset portfolio correlation |
| Spot vs perpetual | Product identity, derivative long/short proposals and plans | Perpetual execution/backtest/replay blocked; long sizing is an unqualified spot-style research estimate. Funding, margin and liquidation contracts absent |

The world is a closed synthetic batch market with random policies, midpoint fills and expiring unmatched orders. It tests accounting and scenario mechanics; it is not a validated model of market response to your actual order. Its synthetic volume must never be combined with exchange volume. Ten thousand agents are not ten thousand real people or independent opinions.

Backtest and replay report assumptions. Gaps can exceed stop-based estimated loss. No profitable outcome, calibrated probability or completeness of the entire original plan is claimed. The demo intentionally may contain zero backtest fills: its only breakout is the final bar, so no next-bar fill is possible.

## Reliability and verification

Single-writer mutations use an exclusive workspace lock and atomic artifact replacement. The ledger is authoritative; portfolio and orders are recoverable projections. A killed process can leave `.writer.lock`: inspect its recorded PID and actual process before manually removing an abandoned lock. Never delete a live writer's lock. There is no stale-lock auto-steal.

Hashes provide change detection, not a security boundary against someone who can rewrite artifacts and hashes. Historical `--now` is an intentional simulation clock; it is not a way to relabel old data as current. Paper submit does not start monitoring. Run explicit `paper watch --duration-seconds 60 --poll-seconds 15` for bounded automatic paper SL/TP checks, or use an explicit close. No process continues after watch completion.

```powershell
python -m unittest discover -s tests -v
python -m compileall -q crypto_skills skills run.py
```

See [artifact contract](references/artifacts.md), [implementation scope](IMPLEMENTATION.md) and [verification evidence](VERIFICATION.md).

## Strategy research update

A bounded60-day BTC/ETH/SOL pilot now supports resumable historical acquisition, frozen four-variant selection, disjoint train/validation/test windows, source/code hashes, held-out-date reuse protection, cost stress and daily block-bootstrap uncertainty. The first pilot was rejected; no profitable strategy or probability increase is demonstrated. See [research results](PROFIT-RESEARCH-RESULTS.md) and [validation workflow](references/validation.md). Manual paper execution tests remain separate, and bounded paper exit checks require an explicit watch command.

## Bounded paper-exit monitoring

`python skills/crypto-paper/scripts/paper.py watch --workspace <paper-workspace> --duration-seconds 60 --poll-seconds 15` checks all existing supported BTC/ETH/SOL Binance spot positions. It uses fresh public bid quotes, recorded levels and per-position cost assumptions; fills are paper simulations at the observed bid minus slip, not retrospective stop prices. Inspect trader/watcher.json and report errors. Monitoring ends at completion. A watcher lease prevents two watcher loops from owning the same workspace; account mutations still use the independent writer lock. See [design](PAPER-EXIT-DESIGN.md) and [verification](PAPER-EXIT-RESULTS.md).

## Delta demo loop work in progress

The Delta integration currently imports the explicitly requested manual BTC
test and provides read-only account/Excel refresh. It does **not** yet enable
autonomous futures entries or implement the 10,000-trade campaign. The
spot-paper commands above cannot operate Delta positions.

`uv run --with delta-exchange-mcp==0.7.2 python -m crypto_skills.delta_ledger`
refreshes `runs/delta-demo-loop/ledger.json`. Credentials stay in the official
MCP credential store. Only `india_testnet` is accepted.

`crypto_skills.delta_observer` provides a bounded read-only loop and workbook
refresh; supply `--node` with the bundled Node executable, optional
`--duration-seconds 60 --poll-seconds 30`. A `runs/delta-demo-loop/STOP` file
stops the observer before its next cycle. Snapshot time is authoritative;
the workbook is a refreshed projection, not a live Excel connection.

`outputs/01a1df70-6789-76b0-9431-f0c905a7987a/trade.xlsx` contains the trade
record and summary. Final net P&L remains blank until settlement, fees and
funding completeness can be established. Every ten finalized trades creates
a distinct research queue record; queueing does not change a strategy.
See [approved limits and remaining tasks](DELTA-LOOP-PLAN.md).
