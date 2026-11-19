# Robustness improvement design

Implements the already requested Plan V1 validation requirements and the owner's new research goal. Decisions below are research design choices, not a promise of profit or a change to account risk limits.

## Approach and scope

Improve evidence quality before adding indicators. Alternatives: expand parameter search (raises selection bias), add agent/news sentiment voting (not calibrated), or build a small reproducible chronological evaluation. Choose the last, because current public-data backtest lost money and lacks held-out evaluation. Manual BTC/ETH/SOL execution-test positions remain untouched and excluded from strategy outcomes.

Python standard library, existing Binance public data-only endpoint, spot long, BTCUSDT/ETHUSDT/SOLUSDT, 5-minute bars. Existing paper constraints/cost assumptions remain: initial cash10000 per independent research account, risk25/order, daily realized loss cutoff100, max order2000, gross cap4000, fees0.1%per side, adverse slip5bps. Independent asset runs are not a synchronized deployable portfolio and must never be reported as the shared live-test ledger. No paid services, leverage, real orders, new background service or large model dependency.

## Audit repair first

Check signal/plan/fill parity. Paper planning anchors stops/targets to the closed signal price; historical code currently recomputes them from next-open fill. Confirm with a failing regression, share long plan-level arithmetic, and skip a next-open fill outside the original plan, matching paper's stop<fill<target requirement. Preserve explicit conservative ambiguous bars, worse stop gaps, both fees, adverse slippage and quantity/tick filters.

## Data and experiment contract

Download a pinned 60-day pilot ending at2026-11-14T00:00:00Z (before the previously inspected real999-bar BTC window, which started later on14November), exactly17280 closed5m bars per asset. Fixed dates, symbol metadata (current filters, historical-rule limitation), acquisition timestamps, raw response pages, gap/duplicate checks and SHA256 manifests are retained. Requests are public, bounded and sequential with a pause between pages; fail and retain a checkpoint on HTTP errors rather than hiding gaps. Resume only matching date range/manifest inputs. Never edit current paper workspaces.

Three contiguous30/15/15-day train/validation/test windows. Flat accounts at each boundary; positions are force-liquidated at the final bar close with exit costs, pending entries expire, and no trade/outcome crosses a split. No future exit is used to discard a trade. Indicator warmup occurs inside each window and is explicitly excluded from trading. This is a conservative disjoint pilot, not full overlapping-label purged CV or an180/30/30-day production study. Document reduced sample/regime coverage.

Predeclare FOUR configurations before any result: baseline lookback20/RVOL0; lookback40/RVOL0; lookback20/RVOL1.5; lookback40/RVOL1.5. Stop1%, target2R remain fixed. Record every train trial. Select the largest average per-asset training net PnL among candidates meeting positive aggregate net and at least30 pooled trades; deterministic ID tie break. If none passes, the highest training score is still frozen for diagnostic comparison, labeled training_failed, never promoted. Validation pass requires at least20 pooled trades, positive mean per-asset net PnL, improvement over baseline mean net PnL and no worse mean drawdown. Validation cannot pick a replacement or retune parameters. Persist the choice before accessing the final test. Final holdout is evaluated only once per frozen manifest/code/settings hash; reuse recorded results on identical reruns and reject changed inputs under an existing identifier. A shared holdout registry reserves final dates and their code/data/config fingerprint. Reusing overlapping final dates for a different experiment is exploratory only and can never qualify; a fresh unseen period is required for qualification.

## Metrics and promotion gate

Per asset and split: trade count, net PnL/return, mean net/trade, win/loss/flat counts, profit factor (null when undefined), equity drawdown, fees, entry notional turnover, cost assumptions. Compare candidate and baseline with identical windows/costs. Cash benchmark is zero; buy-and-hold uses the same order cap with adverse entry/exit slip and both fees, explicitly different exposure/time in market.

Stress the frozen candidate on final test with doubled fees AND slippage; no selection from stressed results. Estimate uncertainty from daily pooled realized PnL, jointly across assets by resampling contiguous three-day blocks (1000 seeded draws); report lower/upper percentile bounds on average daily PnL, dependence and short-sample limitations. This is conditional sampling uncertainty, not next-trade win probability.

Conservative research-qualified status requires: training and validation gates; at least30 final pooled trades; final mean per-asset net>0 and greater than baseline; at least two of three assets profitable; no worse average maximum drawdown than baseline; positive doubled-cost pooled net; bootstrap lower95%bound>0. Otherwise report rejected/insufficient_evidence and leave current entry defaults unchanged. Even a pass qualifies only for a further forward paper pilot, never automatic live execution. No target win rate is fabricated.

## Deliverables and checks

Reusable history/validation Python CLI, shared JSON result envelope, source/data/code hashes, precommitted experiment specification, actual pilot results, skill instructions referencing this evaluation and a narrative report. Unit tests cover boundaries, future data, deterministic selection, holdout immutability, corrupted manifests, accounting/undefined metrics and promotion failures. Run the existing regression suite and fresh offline validation fixtures before network research. Final report distinguishes code correctness, statistical evidence and remaining operational gaps (notably no automatic exit watcher).
