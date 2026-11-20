# Remaining BTC and ETH backtests, round 38

Four strategies received verified historical results. The backlog falls from 228 to 224, with 285 historical tests and 276 source-verified exclusions across the original 785 strategies. The workbook adds 36 result rows and reaches 5,637 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 3301 | Renamed a shadowing identifier and verified the original daily RSI filter, four next-open fills and cash sizing. ETH has one closed lot. The ending BTC and ETH positions are marked separately. |
| 3309 | Replayed the exact polynomial, RSI and order branches with the documented FMZ first-value EMA initialization. Fifteen closed lots and 25 market fills reconcile. The later-initializing Pine Compat EMA is reported as a separate diagnostic because its order history differs. |
| 4681 | Ran the published Python defaults on four recorded Binance Spot symbol windows. The unchanged 60-second loop checked 960 causal quotes and issued zero buy calls under the published zero price ceiling. The benchmark does not provide enabled-buy performance. |
| 5148 | Replayed the authored single-market function on the separately named BTC and ETH futures variants. The stored venue argument is a placeholder. Each variant has 12 primary and 12 delayed paths. ETH market-order admission preserves the published historical 5 USDT minimum, which rejects part of the authored size ladder. |

Four entries received evidence and remain pending.

- #3281 uses newer market-data request spellings in a saved v2 script. A confirmed higher-timeframe control disagrees with the legacy-compatible replay on 24 decision bars.
- #3366 combines fixed exits and a trailing rule. The verified BTC minute path reaches the trailing exit at 33,584.60 on October 24, while the daily model reports 35,134.60 for that path.
- #4111's apparent indicator complexity collapses to high and low series under the saved defaults. Independent frame witnesses show that projecting final daily prices changes 247 gates compared with the previous confirmed day. Partial-day data independently show the future dependency.
- #4762 is valid JavaScript and its publisher settings specify a rolling weekly 796 futures contract. The archived source lacks a dated contract and matching order-book history.

Workbook verification checks all new result rows, coverage cells and the original sheet structure. The repository suite passed 342 tests and 89 subtests. Delta Demo entry hold is active.
