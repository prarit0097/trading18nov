# Remaining BTC and ETH backtests, round 40

Three strategies received verified historical results. The backlog falls from 220 to 217. Of the original 785 strategies, 292 have verified historical scopes and 276 have source-verified exclusions. The workbook adds 12 result rows and reaches 5,644 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 3458 | Replayed the saved Hodrick–Prescott and volume strategy with the documented first-value EMA and a native EMA sensitivity. Independent calculations reproduced the signals, order quantities and cash path. The primary BTC and ETH scopes closed 32 trades with 65.63% after-fee wins and +184,667.76 USDT after modeled fees on 1 million USDT starting equity per market. Pooled realized drawdown was 116,563.41 USDT. |
| 4575 | Confirmed the archived Pine v4 candle and ATR gates, pricing ticks and named brackets against native orders and Binance one-minute data. The BTC conversion alias influences parsed alerts while chart order quantities remain fixed. BTC closed 10 lots and ETH closed 14. Their combined after-fee P&L was −3,247.23 USDT at a modeled 0.075% per side. |
| 5629 | The archived settings select random entries. The original random draws were unrecorded. An independent random-number generator and cash ledger verified 128 seeded paths across the saved and following windows for both markets. The workbook shows the same preselected seed in each scope. The evidence retains the full seed distributions and the modeled fee and execution costs. |

The recorded results apply to their historical windows and fill models. Method details, data hashes, fee assumptions, realized drawdown and terminal inventory are in the evidence files. Delta Demo entry hold is active. The repository suite passed 342 tests and 89 subtests.
