# Remaining BTC and ETH backtests, round 36

Six strategies received verified historical results and the backlog fell from 239 to 233. Of the original 785 entries, 276 now have historical backtest results and 276 have source-verified exclusions. The original workbook gained 33 result rows and reaches 5,628 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 1600 | Independently reproduced all prior UTC-month pivots and next-open settlement on BTC and ETH. A closed-form grid and a run without reporting code agree with the primary run. The 32 modeled fills settle 22 whole-step FIFO lots. The ledger omits three floating-point fragments below the 0.001 quantity step. |
| 3835 | Replayed the saved BTC scope with the sole 50,000 starting-balance literal relocated into the strategy declaration. The default quantity formula rounds to zero throughout 371 BTC days. ETH has positive requested sizes and unsupported undefined-stop behavior, so it remains diagnostic. |
| 4307 | Exact source and independent indicator calculation agree on zero qualifying KDJ signals over the archived 24 days for BTC and ETH. A first-value EMA control also gives zero. Win rate is undefined. |
| 5147, 5149 | The source names BTC and uses a single exchange object in the operative function. These BTC-scoped runs cover 12 recorded-depth benchmarks and 12 additional latency tests per script. All benchmark runs had negative marked P&L after accounting for ending inventory. The original market metadata are a placeholder for #5147 and malformed for #5149. |
| 5150 | The exact archived initial capital and source lot size reproduce 72,000 rejected BTC short attempts in two native historical sessions. The independently checked collateral requirement exceeds the 10,000 USDT initial wallet. There are zero fills, zero P&L and no win rate. |

Three reviewed strategies remain pending.

- #3820 has conflicting original balance settings. Changing the active equity-protection balance from 1,000 to 50,000 moves the first BTC exit and produces materially different ledgers.
- #4650 has opposite zero-quantity priced entries. One runtime reports no closures and another places an exit before the observed entry can occur.
- #5530 passes a Boolean series into a numeric crossover function. Explicit numeric alternatives change the observed ETH signals, while another runtime issues orders despite false gates under its compatible variant.

The preserved reports contain market inputs, fees and replay assumptions. Workbook verification checks all added rows, updated statuses, formatting and the original worksheet structure. The repository suite passed 342 tests and 89 subtests. Delta Demo entry hold is active.
