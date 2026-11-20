# Remaining strategy backtests · Round 12

Seven strategy IDs produced historical closes and added 43 rows. Source review resolved 24 other IDs. The original 785-ID queue now has 393 pending and 392 resolved across Rounds 6–12. The full catalogue has 5,497 tested entries.

## Historical results

- FMZ #183, #721 and #1105 preserve the authored order instructions. The 12-hour CCI, 15-minute RSI and 10-minute candle/RSI tests produced 134 closed lots. #721 had no native or equal-length follow-up closes. Its separate June 2022 expansion recorded two closes. Both Piner execution backends and an independent ledger agreed. [Authored rules and verification](fmz-round12-pine-authored.json)
- FMZ #5708 preserves its archived Pine v1 order and equity behavior on Binance USD-M BTC and ETH. Independent 15-minute control data reproduced all four hourly outcomes. It closed 50 lots and left four positions unsettled. The separate fee sensitivity holds the archived sizing fixed while charging 0.075% per side. Prior-day Coinbase FX converts the realized USD assumptions. [Replay and fee assumptions](fmz-round12-5708.md)
- FMZ #4687 replayed the original configured depth index with a 20-level simulated book. ETH closed 96 lots across two windows. BTC did not submit orders at the archived one-unit sizing and the modeled 10,000 USDT starting cash. [Native EMA evidence](fmz-native-ema-round11.json)
- FMZ #5194 retains the sell-first grid settings on historical HTX spot data, with ETH as a separate cross-asset port. The authored starting balances were unavailable, so the study seeds one base unit and 10,000 USDT in each independent sleeve. The four reconciled receipts cover 429 closed FIFO lots. The report records the different observation policies needed for the synthetic hourly ticks. [Native grid evidence](fmz-native-htx-grid-round11.json)
- OctoBot #6012 tests the published Klinger and Bollinger reversal evaluators with synchronized 30m, 1h and 4h data plus closed one-minute alert samples. The separate BTC and ETH sleeves replace the authored three-pair portfolio and its shared capital. The study reconciled 62 historical simulated fills and 42 closed FIFO allocations, including seed inventory where applicable. [Signal Trading replay and assumptions](nonpine-round12-signal.json) · [Binance archive specification](https://github.com/binance/binance-public-data)

## Source dispositions

Twenty-two IDs are execution, operations or reference artifacts. Each disposition links the exact archived code and identifies the decision path. Two additional IDs are duplicates. #259 preserves #258's trading behavior with different presentation text. #4673 has identical source code and embedded settings to #1320. Their canonical IDs remain pending on the data and runtime requirements in the audit. [Source roles](fmz-native-source-roles-round12.json) · [Dual Thrust comparison](fmz-native-dual-thrust-translation-round12.json) · [Exact source comparison](fmz-native-source-duplicate-round12.json)

## Verification

The repository suite passed 340 tests and 89 subtests. Re-running Round 11's DailyTrading report after sharing the replay engine produced the original bytes. Workbook validation covers all new metrics, all 424 carried-forward statuses, and the expanded result table. The workbook retains win rate, gross and after-cost P&L, fees, and realized drawdown. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round12-coverage.json)
