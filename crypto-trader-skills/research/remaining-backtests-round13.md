# Remaining strategy backtests · Round 13

Six strategies added 34 result rows. Five produced 558 unpooled closed trades. The sixth is a buy-and-hold rule with verified purchases and open inventory. Two OctoBot order-execution modes were resolved through source review. The workbook now has 385 pending of the original 785 IDs and 5,503 tested entries across the full catalogue.

## Historical results

- FMZ #487, #858 and #922 cover the published linear regression, deterministic volume-modulo and Heikin-Ashi channel rules. Both Piner backends and an independent ledger verified 104 closes. The Heikin-Ashi case generates signals on the synthetic series and fills on observed OHLC. [Local series and fill evidence](fmz-round13-pine-local.json)
- FMZ #2864 uses its chart-timeframe VWAP and RSI conditions on Binance USD-M minute bars. Four verified windows closed 366 trades, with one ending position. The report separates the archived zero-fee case from a 0.075% per-side fee sensitivity on the same fills. [VWAP and RSI evidence](fmz-round13-2864.md)
- FMZ #1320 verifies the original ATR setup on two BTC and two ETH perpetual windows. The 88 closed orders reconcile to the native account with less than 0.001 USDT residual in each scope. The workbook records commissions and modeled execution friction separately from signed funding. [Native ATR evidence](fmz-native-atr-perp-round12.json)
- FMZ #1100 preserves the archived limit-buy and hold rule. Four Binance spot windows produced four purchases. The strategy has no sale rule, so the realized win rate is blank. The evidence reports the ending inventory and its marked P&L gross, after fees and after costs without a hypothetical liquidation. [Buy-and-hold evidence](fmz-round13-buy-hold.json)

## Source review and verification

OctoBot #6011 mirrors remote instructions and #6014 executes external TradingView alerts. Both lack an independent authored signal generator. #6010's market-making lifecycle is still pending after checking its profiles, asynchronous fill callbacks and available public feed metadata. [Execution mode evidence](nonpine-round13-source-roles.json)

The repository suite passed 340 tests and 89 subtests. The result table includes fees, net P&L, win rate and realized drawdown. Workbook verification covers the 393 prior candidate statuses and the original result rows. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round13-coverage.json)
