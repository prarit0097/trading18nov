# Remaining BTC and ETH backtests, round 31

Ten replays bring the original backlog to 260 pending. Of the original 785 entries, 249 have historical backtests and 276 have source-verified exclusions. The original `stratergies.xlsx` has 39 additional result rows and 5,601 tested catalogue entries.

| IDs | Historical check |
| --- | --- |
| 226 and 3526 | Saved daily replays use completed 2h DEMA values or completed 15m closes with daily TSI. An independent EMA recurrence and next-open settlement match all 374 closed lots. The authored one-unit exposure and historical margin model can produce losses larger than initial capital. |
| 356 | The January 2024 BTC/ETH portable replay restores the Pine v4 directive. Independent minute chronology checks all 50 closes, with no off-grid price. |
| 2345, 3047 and 4104 | Legacy exit calls specify activation without a trailing offset. The original and isolated runs agree on every order, position, closed lot and equity mark. Saved markets produce 31 closed lots combined. |
| 3530 | Four cases verify the previous completed year's Supertrend context and have one open long each at cutoff. No trades close in those windows. |
| 4545 and 5166 | Verified IIR and ALMA calculations on the source-default history. #4545 yields four closed lots. #5166 has zero eligible entries. |
| 4685 | The original FMZ order template runs over the full ETH date range on native simulated ticks. The published ETH-only mode closes seven lots. The embedded ETH and LTC preset closes six across both legs. The required LTC leg is recorded as part of that preset. |
| 5252 | The independent weekly-merge diagnostic shows active future close exposure in the legacy short flags. This strategy remains pending and adds no performance rows. |

The report digests bind each test scope, data window, commission or fee overlay, and estimated execution model to the coverage update. The workbook comparison checks the new rows, native precision, all original result rows and out-of-scope sheets. Delta Demo entry hold is active.
