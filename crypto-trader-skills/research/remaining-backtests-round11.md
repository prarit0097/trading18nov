# Remaining strategy backtests · Round 11

Seven strategy IDs produced historical closes. Their 40 rows cover 551 unpooled closed lots across BTC and ETH, including FIFO allocations in the OctoBot study. Source review resolved six additional catalogue IDs. The original 785-ID backlog is at 424 pending, with 361 resolved across Rounds 6–11. The full catalogue has 5,490 tested entries.

## Historical results

- FMZ #706 uses the archived R-Breaker order branches and a pinned compatible spot template for its unbound interface. The replay uses a selected one-hour chart, the archived 30-minute filter and one-minute decision sampling. The four independent tests closed 157 lots. [Native R-Breaker evidence](fmz-native-rbreaker-round10.json)
- FMZ #1884 retains the archived daily Playzone rules with verified historical same-context indicator reads. Its native and follow-up tests closed 30 lots. [Playzone evidence](fmz-round11-pine-playzone.json)
- FMZ #410 retains the authored order body on four-hour Heikin-Ashi inputs as a documented standalone variant. #4732 preserves the legacy daily strategy's first intrabar lookup of the previous hour. Independent calculations checked imports, state transitions, fills and fees. The two strategies closed 292 lots combined. [Native chart and reference evidence](fmz-round11-pine-references.json)
- FMZ #5117 and #5514 use lower-timeframe market records to price entries and exits that have explicit stop levels. The replay rechecks market-order behavior and reproduces the priced-stop controls. The eight isolated historical runs closed 63 lots and left two open. The report documents #5514's two-minute candle ownership at chart boundaries. [Priced-stop method and reproduction](fmz-round11-magnifier-priced.md)
- OctoBot #6005 follows the published DailyTrading profile. BTC starts with 10 BTC and 1,000 USDT. The separate ETH scenario substitutes 10 ETH. The replay synchronizes completed 1h, 4h and daily inputs and models orders using one-minute spot data. All 26 fills were checked against the historical candles and the nine closed FIFO allocations were reconciled with independent decimal arithmetic. P&L includes price movement of the seeded holdings after their starting valuation. [OctoBot replay and assumptions](nonpine-round11-daily.json) · [Binance archive specification](https://github.com/binance/binance-public-data)

## Source review and workbook

The archive confirms five one-shot execution utilities and one reusable WebSocket execution template. The utilities place listing or operator-configured ladders or liquidate existing holdings. The WebSocket template exposes execution functions and a test example. None provides the complete position decision rules required for an entry-to-exit performance row. [One-shot tools](fmz-native-one-shot-round11.json) · [WebSocket template](fmz-native-websocket-template-round10.json)

The repository suite passed 339 tests and 89 subtests. Workbook verification covers all new result rows, the carried-forward catalogue statuses and the expanded table range.

The workbook contains gross, after-fee and after-cost P&L, corresponding win rates, and realized drawdown under each replay's assumptions. Results include the source-linked coverage reasons for all 437 IDs reviewed or carried forward. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round11-coverage.json)
