# Remaining BTC and ETH backtests, round 41

Five strategies received verified historical results. The backlog falls from 217 to 212. Of the original 785 strategies, 297 have verified historical scopes and 276 have source-verified exclusions. The workbook adds 22 result rows and reaches 5,649 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 2637 | The source's SPY Coppock curve uses the last confirmed New York session close at the UTC crypto close. The fund sponsor independently confirms all 50 session dates. The saved cold start closes no trades. A separate 40-day prehistory run closes one trade per market and shows +1,596.39 USDT combined after modeled fees. Both runs still have one open lot per market. |
| 2693 | The original ETHUSDT layered EMA source ran through four preselected quote-and-trade windows from January to April 2025. February closes two maker reductions for +0.2616 USDT after fees, with −0.5758 USDT marked P&L including open inventory. The other windows close no trades. Maker fill sizes were modeled from signed trades and cross-checked against official trade IDs. Historical queue position is unavailable. |
| 2833 | All verified FXCM bid and ask prices put the EUR/USD Fibonacci band below the BTC and ETH price ranges. The FXCM archive for July 3–7 is empty. The ECB's daily rates corroborate the price scale through that gap. The archived rules enter one long on each market and neither meets the authored short reversal. Realized win rate is unavailable and both positions remain open at cutoff. |
| 3749 | Official raw BTC trades confirm the daily file for all 100 minute discrepancies with the monthly archive. A scoped repair ties take-profits to their originating entry so a stale limit cannot close a later opposite position. The verified BTC and ETH model closes 57 lots for −1,020.22 USDT after modeled fees. The hosted FMZ output remains unverified. |
| 5230 | A real 0.001-unit lot model removes a fractional residue the compatibility broker counted against the pyramiding cap. Six independent gates match on 40,320 one-minute bars. The two BTC and ETH windows close 181 lots. The archived window loses $882.98 after author fees and the following window loses $11,654.03 after fees. |

The workbook reports realized P&L and drawdown for closed trades. Evidence files carry the open inventory marks, source and data hashes, and model assumptions. Delta Demo entry hold is active. The repository suite passed 342 tests and 89 subtests.
