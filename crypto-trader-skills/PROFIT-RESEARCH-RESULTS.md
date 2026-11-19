# Crypto strategy research: first measured improvement cycle

Historical phase-one report. Its original calculation source is preserved in `research/pilot-20261114-60d-v1/frozen-code`; [replay instructions](references/validation.md). Later bounded paper-exit work is documented separately in [PAPER-EXIT-RESULTS.md](PAPER-EXIT-RESULTS.md).

The workflow is more reliable, but this study does **not** demonstrate increased profit probability. The baseline and all four prespecified configurations failed the training profit gate. The least-loss configuration was frozen for diagnostics and also lost money in validation/test. Its qualification is **REJECTED**; no entry defaults were promoted.

## Repairs and new capabilities

- Paper and historical long plans now share signal-close stop/target arithmetic. Next-open fills outside the original plan are skipped instead of resetting the plan. Worse gap stops and conservative ambiguous-bar exits remain.
- Resumable public historical download, exact continuous UTC bars, raw page envelopes and source/data/code hashes.
- Precommitted four-variant search; chronological30/15/15-day splits; flat boundary liquidation with exit costs; frozen choice; no validation replacement or final-test retuning.
- Shared registry tracks every inspected train/validation/test range. Overlapping later tests with a different fingerprint are exploratory and cannot qualify.
- Cost-inclusive expectancy, win/loss counts, profit factor, drawdown, turnover, cash/capped-hold benchmarks, doubled costs and dependence-aware daily block-bootstrap diagnostics.
- Existing shared manual paper account is separate and unchanged. This study submitted zero orders.

## Data and study design

Public Binance BTCUSDT, ETHUSDT and SOLUSDT spot, 5-minute OHLCV. 17,280 closed bars per asset;51,840 total. Fixed pilot 2026-09-15 through2026-11-14 UTC;30 days train, 15 validation, 15 test. Its end predates the known previously inspected real999-bar BTC window. A short pilot with limited regimes is not a production 180/30/30-day or full walk-forward qualification.

Each asset is simulated independently with 10,000 USDT cash, 25 USDT trade risk, 100 USDT daily realized-loss cutoff, 2,000 USDT order cap and 4,000 USDT exposure cap. Costs assume 0.1% per side and 5 bps adverse slippage per side; historical spread/depth and account fee tiers are not available. These runs are not the actual shared 10,000 USDT manual-paper portfolio.

## Every training trial

| Configuration | Mean per-asset net PnL USDT | Pooled closed trades | Training gate |
|---|---:|---:|---|
| baseline | -262.85 | 168 | FAIL |
| longer | -213.17 | 148 | FAIL |
| longer_volume | -241.41 | 126 | FAIL |
| volume | -263.01 | 147 | FAIL |

IDs: baseline=lookback20/RVOL0; longer=40/0; volume=20/1.5; longer_volume=40/1.5. Stop 1%, target 2R and risk rules fixed. The frozen diagnostic choice was **longer**. Its training_pass is false; it was never considered a qualified strategy.

## Final test: 2026-10-30 to2026-11-14 UTC

| Asset | Baseline net USDT | Candidate net USDT | Candidate trades | Candidate win rate | Doubled-cost candidate net |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | -251.93 | -176.95 | 14 | 21.43% | -209.48 |
| ETHUSDT | -164.11 | -96.40 | 20 | 35.00% | -172.28 |
| SOLUSDT | -341.01 | -364.15 | 26 | 19.23% | -417.72 |

Mean per-asset net: baseline -252.35 USDT; candidate -212.50 USDT. Smaller mean loss is not profitability. SOL worsened. Candidate pooled descriptive win rate: 15/60=25.00%; baseline 19/74=25.68%. These are observed frequencies, not calibrated future probabilities.

Validation also lost money on all three assets. Doubled fee/slippage test remained negative. The 95% percentile block-bootstrap interval on pooled daily mean realized PnL was [-61.48,-15.60] USDT/day across three independent research accounts; 15 daily observations, contiguous 3-day blocks, 1,000 draws, seed 19. This conditional short-sample interval does not remove regime uncertainty or multiple-testing risk.

## Decision and operational boundaries

Reject promotion. Keep current defaults labeled unqualified; do not force trades to manufacture a hit rate. No new indicator or candidate was added after seeing the final outcome. Reusing these inspected dates for different rules is exploratory. Further claims need a separately declared hypothesis, fresh unseen dates and forward-paper observation.

The ordinary paper execution CLI is still available for explicitly requested execution tests. The research gate controls research qualification; it is not a global execution kill switch. The current manually opened BTC/ETH/SOL positions were not altered. No automatic protective-exit watcher or continuous background collection was added. This remains an operational limitation, and bar backtests do not validate exchange queue, depth, impact, latency or real fills.

## Reproduce and inspect

[Commands and qualification policy](references/validation.md) · [Design](PROFIT-RESEARCH-DESIGN.md) · [Implementation plan](PROFIT-RESEARCH-PLAN.md)

[Frozen specification](research/pilot-20261114-60d-v1/trader/experiment_spec.json), [all training trials and selection](research/pilot-20261114-60d-v1/trader/selection.json), [qualification with full test ledgers](research/pilot-20261114-60d-v1/trader/qualification.json), [compact pilot summary](verification/profit-research/pilot-summary.json), [regression test output](verification/profit-research/unit-tests.txt). Identical reruns reuse the completed result, rather than repeating model selection.

Sources: [official Binance kline specification](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klinecandlestick-data), [market-data-only domain](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md), [Bailey et al., probability of backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). The latter motivates selection-bias caution; no formal PBO estimate was calculated here.

## Final verification

83 tests passed in 37.742 seconds. All 12 skill metadata/links, compilation, frozen-result replay and report integration passed. The manual-paper ledger digest is unchanged. Independent final review found no must-fix issue and confirmed that report figures match the artifacts. [Verification manifest](verification/profit-research/verification.json).
