# Verification evidence

Latest paper-exit phase: [verified watcher](PAPER-EXIT-RESULTS.md),101 passing tests and a completed60-second real-data paper observation. Earlier phases/counts below are historical.

Latest research improvement: [measured results](PROFIT-RESEARCH-RESULTS.md), 83 passing tests, parity repair and rejected chronological pilot. Earlier counts below are historical.

Latest code and installation review: [RECHECK.md](RECHECK.md). Its fresh test log supersedes the historical counts below.

Verified locally on 2026-11-17, Windows, Python 3.13. Runtime requires Python 3.11+ and the standard library; only the development skill validator uses already available PyYAML. No paid-provider call, credential or live exchange order was used.

Subsequent installation verification: all 12 skills registered in local Codex; isolated Python 3.13.5 environment passed all 63 tests in 10.873 seconds and ran a fresh installed-wrapper demo. See [installation details](INSTALLATION.md), [evidence](verification/installation.json) and [setup tests](verification/setup-unit-tests.txt). Original build benchmarks below remain the original recorded runs.

## Automated checks

Run `python -m unittest discover -s tests -v`. Final result: **63 tests passed** in 10.797 seconds. Saved final output: [unit-tests.txt](verification/unit-tests.txt). It exercises:

- Atomic artifacts, schema/digest integrity, missing timestamps, invalid decimals, path kinds and exclusive locking.
- Closed/gapped/duplicate/unclosed OHLCV, explicit units, failed-refresh invalidation and public REST parsing.
- RSS/Atom parsing/import, correction hashes, dedupe, cache/retry/conditional polling, source errors, private address/redirect/body/deadline rejection.
- Lagged entry/RVOL, fee/slippage/step sizing, cash/exposure/minimum notional, risk expiry, original signal age and fills outside stop/target.
- Revalidation under lock, changed account/upstream data, idempotent paper orders, journal projection recovery, close fees/daily loss and backdated mutation rejection.
- Historical next-open fills, ambiguous/gap stops, both-side costs, minimums/exposure/daily loss, unclosed/future bars and perpetual rejection.
- Seeded replay accounting/diversity, transitive lineage, bounded actual 10,000-participant matching and conservation.
- All 12 skill wrappers' help/metadata/relative links, a complete demo, separate processes sharing one workspace, pipeline waiting exit code, explicit close/retry and synthetic/stale-chart behavior.

Official skill-creator `quick_validate.py`: all 12 skill folders valid. Saved [skill-validation.json](verification/skill-validation.json). Python compile check and local Markdown links: [checks.json](verification/checks.json).

Tests validate deterministic tool behavior. They are not a profitable-strategy benchmark, autonomous-agent usability trial or validation against a real exchange matching engine.

## Reproducible offline execution

Final saved demonstration: [summary](verification/demo-summary.json), [research results](verification/research-results.json), workspace `verification/demo-workspace`, and its [chart](verification/demo-workspace/chart.svg). Earlier `demo-workspace` is an initial run; the verification subdirectory contains the final checked run. Fresh run command:

```powershell
python run.py demo --workspace ./another-new-demo
```

Synthetic fixture, seed 19, 160 closed 5-minute bars, fictional limits, simulated clock `2026-11-17T12:00:00Z`:

| Check | Observed result |
|---|---|
| Paper flow | Ready proposal/plan/size, approved risk, one fictional buy, report |
| Backtest | 0 trades, 0 net PnL; sole breakout on final bar correctly has no next-bar fill |
| Scenario replay | 10,000 settled paths, 312 net winners, 9,688 losers, 0 flat |
| Price vs net outcome | 7,572 positive underlying horizons; costs make many net plan outcomes negative |
| Historical pool | 159 return bars, 156 distinct four-bar blocks, 10,000 sampled block sequences |
| Replay elapsed | 0.358962 seconds in this final run; machine-specific, no throughput SLA |
| Synthetic world | 10,000 participants, 20 steps, 200,000 submitted orders, 111,293 matches |
| World accounting | All 10,000 participants traded; cash/inventory conserved; balances nonnegative |
| Synthetic volume | 28.43033 fixture BTC matched; this is not exchange volume |
| World elapsed | 1.002873 seconds in this final run; no scale extrapolation |

Replay winners are conditional counts in synthetic resampled history, **not** an estimated probability of your next BTC trade winning. A 10,000-participant random economy is not MiroFish, an LLM society or independent human validation. Paper risk approvals are historical snapshots; after a paper fill changes the account, old risk inputs are expected to show changed account lineage. Obtain a fresh approval for another order.

## Public read-only smoke checks

- [Binance market smoke](verification/public-market-smoke.json): passed at `2026-11-17T12:31:30Z`; 29 closed BTC/USDT 5-minute candles, public exchange filters, explicit BTC base volume/USDT price units and valid contiguous health. Fetch elapsed 2.190 seconds. Snapshot read only.
- [Cointelegraph RSS smoke](verification/public-news-direct-smoke.json): HTTP 200, 30 items, source status `ok`, elapsed 0.302 seconds at `12:32:08Z`. This measures one request, not time from event/publication to delivery. No feed is enabled in the default config.
- [CoinDesk RSS attempt](verification/public-news-smoke.json): unavailable because the endpoint redirected and the collector intentionally rejects redirects. The failure was recorded in source health. A canonical direct feed URL must be configured and revalidated before using that source.

Network timing, feed availability, source publishing lag and exchange filters can change. The collector is a one-shot snapshot/poll, not a continuous service. News requests have an eight-second socket/transport deadline after DNS resolution; DNS timing remains platform-controlled. Server cache/retry waits are capped at seven days. No fastest-news or availability claim follows from these checks.

## Deliberate limits

No live order connector, protective exit watcher, authenticated account connector, persistent WebSocket/L2 archive, full historical pagination, walk-forward validation, calibrated profit probability or real MiroFish integration is included. Local skill registration was completed in the subsequent setup. Perpetual proposals/plans are research-only; qualified derivatives execution/backtesting/replay remains blocked. Long derivative sizing can produce a spot-style research estimate, which never qualifies margin/funding/liquidation risk or authorizes execution.

No original analysis document or upstream repository was modified. This directory is the standalone deliverable. [README](README.md) maps the implemented capabilities to the broader original plan.
