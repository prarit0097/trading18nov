# Remaining strategy backtests · Round 9

Round 8 left 472 catalogue IDs pending. This pass continued native FMZ broker replays, exact Pine timeframe recovery and an OctoBot profile-based study.

This pass verified seven additional strategy IDs and added 40 result rows. Six had closed lots and one completed with zero realized closes. The original 785-ID backlog is now at 465 pending, with 320 resolved across Rounds 6–9. The overall catalogue has 5,473 tested entries.

## Verified backtests

- FMZ #696 preserves the author's absolute grid levels within two historical OKX windows from the archived test period. BTC produced closed lots in both windows. The same unchanged grid produced no ETH orders. The archived OKEx alias and recovered OKX historical data are documented in the receipt report. [OKX grid evidence](fmz-native-okx-archive-round9.json)
- FMZ #941 checks the published settings on BTC and ETH using the broker's documented Binance account shape. The source uses BNB, so the BTC/ETH results are labeled as a market port. The replay reconciled fills and open inventory with zero realized closes. [Grid example evidence](fmz-native-grid-example-round9.json)
- FMZ #3698 replays the historical Bitfinex random-forest strategy. It records a native model and broker provenance and reconciled cash, inventory and closed lots. [Bitfinex evidence](fmz-native-bitfinex-forest-round9.json)
- The Pine replays cover the archived Heikin-Ashi wave counter, the three-candle reversal and the Alligator setup. Their individual-market rows have 205 closed lots. Entry timing and indicators were checked separately from broker settlement, including Pine v5's eager history evaluation where needed. Starting equity and trade sizes follow each archived source. The realized BTC reference drawdown for #5582 exceeds its starting equity in that broker model. [Wave evidence](fmz-round8-pine-wave.json) · [Three-candle evidence](fmz-round9-pine-double.json) · [Alligator evidence](fmz-round9-pine-alligator.json)
- OctoBot #6007 uses the pinned Dip Analyser profile's four-hour Klinger and RSI rules, sampled one-minute fluctuation trigger, and weighted profit ladder. It tests BTCUSDT and ETHUSDT separately with 1,000 USDT each through the source's single-asset branch. The original shared profile has pre-existing BTC and an additional ETH/BTC pair. The variant uses later-minute strict trade-through, available bar volume and documented passive-fill assumptions. An independent audit checked all 30 closed lots, cash and volume on the source candles. Window end dates are exclusive at UTC midnight. The source default stop is disabled. Reported P&L and drawdown use realized exits, and the workbook also records unsettled lots. [OctoBot evidence](nonpine-round9-dip.json)

## Verification

The workbook checks matched all 40 new result rows, the 472 candidate statuses, previous result rows and the resized table. The repository suite passed 334 tests and 89 subtests.

## Remaining inputs

Eight further native sources have updated evidence about the exact blocked execution layer, including archived subscriptions, missing templates, inverse or expiry-specific settings and missing adapter fields. Their IDs are still pending. [Source evidence](fmz-native-round9-source-blockers.json) · [Per-strategy audit](remaining-backtest-round9-coverage.json)

Delta Demo remains paused.
