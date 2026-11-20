# Remaining strategy backtests · Round 10

Round 9 left 465 catalogue IDs pending. This pass recovered additional native timeframes, corrected a broker sizing discrepancy, verified an archived Bitfinex model and checked protocol settlement from public receipts.

This pass verified ten strategy IDs and added 55 result rows. Source review resolved 18 additional IDs as execution libraries or API examples. The original 785-ID backlog is at 437 pending, with 348 resolved across Rounds 6–10. The overall catalogue has 5,483 tested entries.

## Replay methods and evidence

- The Pine native chart studies cover #3391, #2609, #5274 and #5704. The first independently verifies delayed Heikin-Ashi inputs and one-minute exit sequencing. The legacy group independently checks recursive state, ATR, Donchian conditions, original order timing and fees. #5274 retains its original window with no closes. Its follow-up was extended after an initial 30-day follow-up also produced no signals. [Smoothed Heikin-Ashi evidence](fmz-round10-pine-smoothed.json) · [Legacy evidence](fmz-round10-pine-legacy.json)
- The chart-source cohort verifies #1375 on its saved hourly bars and #1768 on its daily bars. The latter required a long lookback and produced closes only in its extended 500-day validation window. Its original native interval and period remain recorded. [Chart-source evidence](fmz-round10-pine-chart.json)
- FMZ #4721 and #5520 use an offline patch to the pinned Pine Compat Runtime. The archived percentage allocation now uses the price available at the market order's fill. Twelve broker fixtures pass after the patch, including the six sizing checks that failed on the original runtime. Eight BTC and ETH archive runs also reconcile independently and produced 106 unpooled closed lots. [Bar Magnifier replay and reproducibility](fmz-round10-magnifier-market.md)
- FMZ #688 is the archived Bitfinex SVM study. The broker cash, fills and inventory reconcile independently across BTC/USD and ETH/USD. The later BTC sample closed two lots. The other market windows have no realized closes. [Native model evidence](fmz-native-bitfinex-svm-round10.json)
- Opyn #6173 replays one actual ETH deposit that minted Crab shares and oSQTH. The modeled hedge uses the first later sufficiently sized observed oSQTH sale. The share payout uses the conservative end of 31 observed shutdown redemptions. Gross P&L adds back the nominal swap fee, and net results include observed transaction gas and a historical median redemption gas cost. The workbook reports the result in ETH. This one-lot scenario retains exposure for about four hours between the mint and the later hedge. [Crab evidence](nonpine-round10-crab.json)

## Verification

The repository suite passed 336 tests and 89 subtests. Workbook verification checks the added rows, the 465 prior candidate statuses and preservation of the original table entries.

## Source review

The archive and publisher profiles confirmed 18 entries were execution libraries or API examples. Their coverage statuses cite the callable functions and the scope of each example. Some execute an externally chosen instruction or a manual example. They supply no independent historical decision rule. The caller for #4547 remains pending with its missing template recorded. [Execution libraries](fmz-native-api-library-round10.json) · [Standalone source review](fmz-native-standalone-role-round10.json) · [API examples](fmz-native-api-examples-round10.json) · [Adapter examples](fmz-native-api-adapters-round10.json)

The workbook includes win rate, P&L before fees, P&L after fees, P&L after all modeled costs and realized drawdown. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round10-coverage.json)
