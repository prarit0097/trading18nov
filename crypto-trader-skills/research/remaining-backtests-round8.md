# Remaining strategy backtests · Round 8

The Round 7 checkpoint left 480 catalogue IDs pending. This pass targeted archived FMZ settings, original-timeframe Pine feeds and protocol settlement histories.

Round 8 adds 38 result rows from seven strategies. Six had closed lots, and one completed with zero closes. Source review also resolved one catalogue entry as an API demonstration. The original 785-ID backlog is at 472 pending, with 313 resolved across Rounds 6–8. The overall catalogue has 5,466 tested entries.

## Historical replay methods

- FMZ recovered the published EMA settings and completed the last ETH windows for #2465 and #2519. Both reports reconcile the archived BTC and ETH orders against the independent cash and inventory calculation. #575 is a seeded inventory exit study. It uses the original Bitfinex BTC/USD conditions and a separately labeled ETH/USD port. Entry inventory is supplied by the archived configuration. [Native Python receipts](fmz-native-python-round8-supplement.json) · [Bitfinex receipts](fmz-native-bitfinex-round8-supplement.json)
- The native-timeframe Pine studies preserve the original hourly Heikin-Ashi or two-hour ZigZag logic. The Heikin-Ashi replay checks the requested prices against each provider candle's OHLC average. The ZigZag replay verifies the lower-timeframe input and the legacy recursive state before accepting the historical run. [Hourly Heikin-Ashi evidence](fmz-round8-pine-native.json) · [ZigZag evidence](fmz-round8-pine-zigzag.json)
- The original #5540 entry sizing reads account equity. The alternate engine uses the archived strategy, verified Binance USD-M one-minute and ten-second history, exchange tick and quantity settings and Coinbase's previous-day USDT/USD close. The workbook identifies the FX source so this variant can be evaluated against the same inputs. [FX replay and reconciliation](fmz-round8-fx.md) · [Recovered lower-timeframe input](fmz-round7-magnifier-followup.md)
- Opyn #6172 uses 27 observed WETH-to-oSQTH swaps and the exact November 4, 2024 shutdown formula. All 37 sampled controller redemptions match the integer settlement calculation. After-fee P&L uses the actual WETH input and settlement proceeds. Gross P&L adds back a modeled pool fee. Net P&L includes observed entry gas and a historical median redemption gas estimate. The scenario amounts are in ETH, with realized drawdown at shutdown. [Opyn shutdown announcement](https://medium.com/opyn/squeeth-has-shutdown-a8a3c2869eaa) · [On-chain evidence](nonpine-round8-squeeth.json)

The source review for #699 identified reads and an API cancellation example, with no order entry path. The status is recorded alongside the audit evidence. [FMZ API example review](fmz-native-round8-api-demo-coverage.json)

## Verification

Workbook verification checked the 38 added result rows, all 480 candidate statuses, the previous result rows and the table range. The repository suite passed 332 tests and 89 subtests.

The workbook separates studies with closed lots from valid runs without closes. Blank win-rate cells indicate no realized denominator. Unqualified strategies retain a concrete reason and source in the coverage sheet. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round8-coverage.json)
