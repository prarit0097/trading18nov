# FMZ #4063 quarter-end confirmation

The saved Pine v4 strategy compares the current three-month high and low with the previous quarter's. It uses a $20,000 starting balance, sizes entries at 100% of simulated equity, and reverses on opposite signals. The source exposes a `lookahead` option. The verified benchmark sets that option to `false` and retains the saved `3M` resolution and `offset=0`. It covers 371 daily bars on each Binance USD-M market from November 14, 2022 to November 20, 2023 exclusive. BTCUSDT is the archived contract. ETHUSDT uses the same rules and interval. [FMZ source and configuration](https://www.fmz.com/strategy/432807)

## Saved-default diagnostic

The saved `lookahead=true, offset=0` publishes the completed quarter's range to earlier daily bars. It showed extrema unavailable at the decision time on 275 BTC bars and 252 ETH bars. Comparing those decisions with each developing quarter's ranges as of the day's close changes 86 BTC signals and 108 ETH signals. On January 1, 2023 the saved defaults see the quarter's BTC high of 29,184.80 and ETH high of 1,860.00. At the close that day, those highs were 16,618.80 and 1,204.79. The report excludes performance derived from the saved settings. [TradingView historical lookahead semantics](https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/#lookahead)

## Verified `lookahead=false` benchmark

| Market | Closed trades | Win rate | Gross P&L | After-fee P&L | After-fee drawdown | Positions left open |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 1 | 0.00% | −14,408.02 | −14,413.46 | 14,413.46 | 1 |
| ETHUSDT | 1 | 0.00% | −1,654.48 | −1,658.31 | 1,658.31 | 1 |
| Pooled closed-trade sequence | 2 | 0.00% | −16,062.49 | −16,071.77 | 16,071.77 | 2 |

Amounts are in USDT. Drawdown uses realized, closed-trade P&L. All four market-order fills match the first hourly opening prices of their respective days. Each actual quarterly range reconciles against the official daily history. The independent ledger reproduced each order, its whole-lot size, both settled trades and 742 daily cash, marked inventory and equity records against the pinned Pine runtime. The sizing counts opening fees in the new position budget and posts the reversal fee on the full executed quantity. The source commission of 0.01% per side applies. The test does not model funding, spread, slippage, liquidation or live host behavior. [Binance archive data and published checksum format](https://github.com/binance/binance-public-data)

The final BTC long had 1,748.54 in unrealized gross P&L. The final ETH short had −3,758.69. Both remain outside the closed-trade table. Two closed trades provide little evidence about expected returns.

## Reproduction

1. Pin source commit `7853bb2bf262c4567ac238d3552d97f0e50cb801` and stage the saved document as `source-4063.md`. Verify the source and offline Pine runtime hashes in the JSON report.
2. Run `python -m research.fmz_round50_4063_stage DAILY_DIR [ADDITIONAL_DAILY_DIRS ...] SANDBOX/4063-feed.json`. The directory inputs contain official Binance daily zip files and their checksum receipts. The preparation includes completed quarterly context before and after the scoring window for the saved-default diagnostic. The source option only receives a completed quarter at or after the last daily close in that quarter.
3. Run `fmz_round50_4063_runner.py` in the existing Windows AppContainer with `replay_2864.py`, `probe_1216.py` and the staged source and market feed. Its native literal run provides the saved-default diagnostic. The second run sets the source input to the other documented value.
4. Run `python -m research.fmz_round50_4063 SANDBOX HOURLY_ARCHIVES OUTPUT_JSON`. The finalizer checks every signal series independently, verifies execution-day child bars and cross-checks the fills and marked ledger. `fmz-round50-4063.json` records reproducible evidence for both modes and performance rows only for the confirmed mode.
