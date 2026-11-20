# Remaining BTC and ETH backtests, round 37

Five strategies received verified historical results, reducing the original backlog from 233 to 228. Of the original 785 entries, 281 now have historical backtests and 276 have source-verified exclusions. The workbook gained 27 result rows and now has 5,633 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 365 | Selected the source's declared EMA default with the FMZ-documented initialization. Venue minute bars and historical EUR conversion independently reconcile 2,684 closed lots in the two markets and two windows. The source fixes each order quantity at 10,000 underlying units and uses no broker margin requirement, so exposures are much larger than the starting account. |
| 1807 | Preserved legacy eager evaluation, repaired source identifier and type conflicts, and verified the active default long-only gates. Four BTC and ETH lots close through eight next-open fills. |
| 2364 | Recovered archived alias spellings and tested alternate nested-request evaluation and prefix timing. The measured model has 20 closures, 42 next-open fills and two open lots. |
| 4651 | Replayed the exact Pine v4 body and matched its outputs to two compatibility controls, including one-minute fills. The original rule's uninitialized price references create several same-open zero-distance exits that incur source commissions. Twenty-seven lots close. One modeled ETH limit has finer precision than the venue tick. A tick on the admissible side was also reached in the same first qualifying minute. |
| 5774 | Replayed the explicitly named ETHUSDT variant on recorded top-five futures depth. Default saved market metadata are a placeholder. Twelve main and twelve delayed runs preserve the original simultaneous long/short logic and long-first position selection. |

#2954 remains pending. Removing identical duplicate defaults repairs compilation, and confirmed and legacy weekly variants show the same opening fills in the tested engine. The disabled side still submits a priced zero-quantity order. The variants disagree on four later ETH stop touches, so the original position-closing behavior remains unresolved.

The workbook checks cover all added results, updated coverage cells, formatted cost and drawdown columns and preservation of other sheets. The repository test suite passed 342 tests and 89 subtests. Delta Demo entry hold is active.
