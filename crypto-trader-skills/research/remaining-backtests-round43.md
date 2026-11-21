# Remaining BTC and ETH backtests, round 43

Five strategies received verified historical results. The backlog falls from 206 to 201. Of the original 785 strategies, 308 have verified historical scopes and 276 have source-verified exclusions. The workbook adds 22 result rows and reaches 5,660 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 634 | Used the author's non-repainting delay setting on the one-hour chart. The preceding three-hour SMMA data were already confirmed at every signal. The saved zero delay changes 44 BTC and 56 ETH alert bars. The delayed model settles 58 trades for +1,787.83 USDT after modeled fees and leaves two open. |
| 2575 | Independent five-bar pivots and ABCD conditions match both clock controls and the original hourly orders. The archived window closes no trades. The following window closes seven for +199.64 USDT after fees and +70.89 USDT after the additional execution allowance. |
| 3038 | Replayed the authored waiting bracket using observed one-minute and raw trade chronology. Raw ETH prints put the first eligible entry after the entry candle's high. BTC and ETH both reach their targets before the next daily decision. The two observed sizing conventions yield pooled after-fee P&L of +$1.4354 and +$1.4521 in separate scenarios. Hosted fill parity and queue priority remain unresolved. |
| 3697 | The original coin flips and wait draws are unrecorded. Verified 128 explicitly seeded paths against independent decision and financial ledgers. The preselected workbook seed closes 40 trades in the saved window and 44 in the following window. Pooled after-fee P&L moves from −11,839.40 to +31,006.68 USDT. |
| 3717 | Replayed the saved Binance BTC spot grid's launch day from recorded depth and signed trades with an explicit maker-fill model. There are 127 FIFO closed sells, with a 54.33% after-fee win rate, −3,321.70 USDT realized P&L and −14,359.93 USDT marked P&L from 1 million USDT starting equity. The realized drawdown was 0.55% and the marked drawdown was 2.84%. The workbook preview caught percentage-point units that were corrected by independently rebuilding the results as decimal fractions. |

Workbook performance applies to its stated instrument, window and assumptions. Open inventory and marks stay outside realized statistics. Delta Demo entry hold is active. The repository suite passed 342 tests and 89 subtests.
