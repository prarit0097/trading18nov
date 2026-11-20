# Remaining BTC and ETH backtests, round 33

Six verified replays reduce the original backlog from 252 to 246. Of the original 785 entries, 263 now have historical backtests and 276 have source-verified exclusions. The original `stratergies.xlsx` contains 24 additional result rows and 5,615 tested catalogue entries.

| ID | Verified scope |
| --- | --- |
| 564 | Confirmed 5m inputs and independent daily entry gates. The raw interpreter leaves both positions open. The documented trailing replay closes both using the first qualifying minute price path and the original fee schedule. |
| 1598 | Preserved grid position accounting, historical four-week pivots and order-on-close behavior. Eleven FIFO fragments settle before the authored 05:20 UTC terminal cutoff. The source uses a 500,000 sizing balance and separately declares 10,000 broker capital. |
| 2708 | Fifteen closed lots across archived BTC data and matched ETH. Raw market prices, source Heikin-Ashi and Supertrend signals, and exchange clock conditions reconcile. |
| 4821 | Restored the original commented declaration and verified confirmed nested four-hour EMA, Bollinger and ATR rules. Eleven market-exit lots settle in the measured scopes. |
| 4899 | Three archived-window ETH sessions produce 868 closed reductions from exact source execution in the FMZ simulated fill model. 693 of 1,756 modeled prices fall within the corresponding observed Binance minute range. Both marked and closed drawdown are included in the report. |
| 5486 | Verified 117 source bracket closures using causal minute paths, source cash fees and three-tick slippage. Two archive OHLC differences occur outside the applicable session with no exposed order or position. |

The #3038 replay remains pending. Official minute and trade chronology resolve its first price paths, while the archived unnamed exit attachment and order-sizing behavior vary across broker interpretations.

Each report identifies its data source, fee schedule, and execution model. The workbook comparison verifies the full result table, updated coverage cells and untouched sheets. Delta Demo entry hold is active.
