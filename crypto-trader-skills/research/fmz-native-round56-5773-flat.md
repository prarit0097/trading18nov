# FMZ #5773 short flat compatibility replay

The author specifies one-way Binance USDT perpetuals. The pinned source on the native engine aborts before its first polling cycle because the simulator account omits `Info.totalWalletBalance`. This matches the public report of the same startup error. The sole access to that field is an argument to `LogProfit`. The compatibility run uses the flat simulated balance for that log and supplies the documented Underscore operations over the actual finite arrays. No entry, sizing, cancellation, price or signal expression changes. [Published strategy](https://www.fmz.com/strategy/260806) · [Author explanation and startup discussion](https://www.fmz.com/bbs-topic/6611) · [Documented JavaScript helpers](https://www.fmz.com/user-guide/built-in-libraries/javascript-libraries)

Both markets use the first 60 seconds of the November 19, 2026 noon UTC archive period previously selected for the strategy research. The replay reads timestamped Binance USD-M depth and trade prints from FMZ, with ten book levels and complete native preload. The isolated native engine uses those stored market events and its backtest execution clock. It records three passive sells and three successful cancellations. Every accepted limit stays above both the best observed bid and highest trade print from 200 ms before submission through 200 ms after cancellation. [FMZ real-tick mode](https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching)

| Market | Canceled sell attempts | Filled orders | Closed trades | Net USDT | Closed drawdown USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT perpetual | 1 | 0 | 0 | 0 | 0 |
| ETHUSDT perpetual | 2 | 0 | 0 | 0 | 0 |

Each simulated account stayed flat with 10,000 USDT. Win rate is undefined. This minute does not exercise maker queue priority, fees, or one-way reversal behavior after a fill. Those paths need another verified scope before evaluating performance.

Reproduce by staging the pinned Markdown and recorded data with `fmz_native_round56_5773_stage.py ARCHIVED_MARKDOWN APP_CONTAINER_ROOT/r50-5773-pilot-input.json.gz`. In the existing Node AppContainer, run `fmz_native_round56_5773_worker.cjs` with each of `literal`, `display` and `compatibility`. Then run `fmz_native_round56_5773.py APP_CONTAINER_ROOT OUTPUT_JSON` to check the tapes, source calls, cash and cancellations. The raw archives and runtime stay outside Git.
