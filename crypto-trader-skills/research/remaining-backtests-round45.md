# Remaining BTC and ETH backtests, round 45

Six strategies received verified historical results. The backlog falls from 193 to 187. Of the original 785 strategies, 322 have verified historical scopes and 276 have source-verified exclusions. The workbook adds 16 result rows and reaches 5,674 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 3366 | Replayed 347 complete daily decision bars per market plus the final partial day for existing orders. Official one-minute OHLC matches all archived hourly parent prices. Eight checksum-verified raw trade days resolve competing in-minute exit paths. The tests for carrying and restarting the active trail at daily amendments generate the same ledger. There are 22 total closed lots with +664.76 USDT pooled P&L after modeled fees. |
| 4052 | An exact whole-lot replay removes a fractional residual that otherwise prevented further ETH orders. Venue tick alignment and strict observed five-minute trade-through reconcile the 69 settled lots with independent cash, position and equity calculations. Pooled P&L is +10,467.59 USDT after modeled fees and one position remains open. |
| 4417 | Replayed the author's published BTC and ETH three-leg butterfly notebook. The notebook models the COIN-M prices using USDT-linear accounting. Closed after-fee P&L is +780.29 USDT on BTC and +187.03 USDT on ETH. Authenticated price inputs and terminal-value and fee sensitivities are reported. Actual inverse contract execution and funding are outside the notebook scope. |
| 4427 | The original notebook's BTC hedge and 14 specified altcoin shorts generate 4,085 closed leg reductions. Its closed result is +5,599.82 USDT after fees and +5,603.34 USDT including the author's proxy funding. The model starts from the notebook's allocations and uses the archived historical fee and carry rules. |
| 4428 | Reproduced the author's hourly relative-value EMA notebook on the published 23-asset universe. BTC supplies the reference and is excluded from traded legs. The model closes 16,537 leg reductions for +9,749.13 USDT after fees and allocated proxy funding. The author's ETH leg alone is negative before fees. |
| 4432 | Verified WaveTrend signals with FMZ's documented first-sample EMA recurrence. Unused charts and visual feeds do not affect the order journal. The two modeled windows close 15 reversal lots, carry four at cutoff, and produce pooled after-fee P&L of −1,103.19 and −5,684.23 USDT. |

The original Boolean operands and mixed-version order semantics remain unresolved for #4098 and #5530. Their evidence updates carry no P&L rows. Source and market receipts, fill and fee assumptions and terminal inventory are documented in the individual reports.

Delta Demo entry hold is active. The repository suite passed 342 tests and 89 subtests.
