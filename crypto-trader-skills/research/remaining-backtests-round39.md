# Remaining BTC and ETH backtests, round 39

Four strategies received verified historical results. The backlog falls from 224 to 220. Of the original 785 strategies, 289 have verified historical scopes and 276 have source-verified exclusions. The workbook adds 14 result rows and reaches 5,641 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 388 | Recovered the archived sibling-entry logic and verified both compiled signal paths. Official one-minute and 15-minute chart parents agree. A separate price-path model uses per-entry bracket references, FIFO accounting, causal percent sizing and the source commission. It settles 207 lots and leaves two open. A sandbox fixture confirms next-open market priority for the primary model. Switching priority changes ETH net P&L slightly, recorded separately. |
| 4016 | The exact saved 24-hour run starts without enough history for the 100-bar Hodrick–Prescott filter and produces zero orders on BTC and ETH. A separate run with 120 confirmed prehistory hours and no orders before the scored day settles three trades. Both initialization scopes are reported. |
| 4026 | Exact legacy lower-timeframe selection, RSI calculations and 57 named bracket exits agree with the independently verified minute paths. Two BTC exits that looked profitable in the chart-only model are stops under the finer data. |
| 5153 | The exact archived BTC futures settings ran against recorded quotes and signed trades. Resting maker orders require price-through volume in the simulator, with additional stricter-volume controls. The recorded trade witnesses match official Binance aggregate trade IDs. May closes two reductions and June closes none. Real historical queue position is unavailable, and these windows exercise the long side. |

Two entries remain pending.

- #1847's original three terminal spot buy failures are consistent with insufficient quote cash for commission even though the gross requests fit. A fourth scope stops in its opening branch without those rejections.
- #5978's official Grid Strike simulator derives levels from the launch candle's close and fills grid orders inside that same candle. Across two observed spot days, 29 of 31 reported buys are above the entire quoted candle high. Changing activation, pacing, leverage and order limits together leaves the simulator results identical. The diagnostic contributes no performance rows.

Workbook verification checks all new rows and coverage statuses while preserving the original sheet structure. The repository suite passed 342 tests and 89 subtests. Delta Demo entry hold is active.
