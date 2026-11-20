# Remaining BTC and ETH backtests, round 35

Three verified historical scopes reduce the backlog from 242 to 239. Of the original 785 entries, 270 now have historical backtests and 276 have source-verified exclusions. The workbook adds 21 result rows and reaches 5,622 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 197 | Replayed the original BTC futures source on 25 levels of recorded historical order-book depth. All 12 benchmark paths and 12 latency variants completed. The benchmark paths closed 954 reductions, including 509 net winners. Every benchmark path finished with a net loss after fees and funding. |
| 1781 | Restored explicit recursive state and removed an unused higher-timeframe calculation. Both native EMA initializations produced the same order flags and fills on BTC and ETH. Independent code matched 17 fills, 10 closed lots and all equity marks. The report records decision changes under an alternative pivot precision model. |
| 3277 | Switched off the archived reporting-only table and checked the same order logic in isolation. The 15m replay verifies two closed lots and four terminal holdings, along with order-price eligibility, quantities, costs and drawdown. |

Five additional entries received evidence and remain pending.

- #2326 mixes a Pine v2 declaration with newer request syntax. UTC timing witnesses disagree on 64 BTC and 55 ETH crossover bars when the 370m close is projected versus confirmed. The original host's alignment and request behavior remain unknown.
- #2823, #2828 and #3190 rely on disputed initial-capital assignment. The source and runtime evidence show that the host balance directly affects order quantities.
- #5211 has competing exits for the same entry. Tested runtimes disagreed on whether the 20% limit reserves part of the position.

Workbook checks confirmed added result rows, updated coverage cells and preservation of other sheets. The repository suite passed 342 tests and 89 subtests. Delta Demo entry hold is active.
