# FMZ #4699 Cboe put/call publication timing

The archive trades Binance BTCUSDT hourly from September 30 to October 30, 2023 UTC exclusive. The source smooths the Cboe total put/call ratio over 20 hourly observations, then computes a second 30-bar average and deviation bands. The first long is submitted when the fast series crosses below the upper band. TradingView identifies the requested `USI:PCC` as the combined equities-and-indices Cboe ratio. [Saved FMZ Pine strategy](https://www.fmz.com/strategy/430668) [TradingView symbol identity](https://www.tradingview.com/symbols/USI-PCC/)

Cboe’s official dated forms yield all 24 sessions required for this cold-start replay and its availability controls. The Oct. 4 record reports a total ratio of 1.59. The saved strategy and the dated forms do not document when the 2023 daily value reached the hourly TradingView or FMZ stream. The data values are known. Their time of availability remains unresolved. [Cboe selected-date market statistics](https://www.cboe.com/markets/us/options/market-statistics/daily/?dt=2023-10-04)

| Hypothetical hours from session date at UTC midnight | BTC first entry in USDT | ETH first entry in USDT | BTC native diagnostic closes | ETH native diagnostic closes |
| ---: | ---: | ---: | ---: | ---: |
| 21 | 27,263.80 | 1,649.72 | 8 | 9 |
| 22 | 27,384.50 | 1,656.15 | 7 | 10 |
| 24 | 27,393.30 | 1,656.95 | 7 | 9 |
| 30 | 27,378.60 | 1,638.48 | 5 | 6 |
| 36 | 27,513.10 | 1,645.63 | 5 | 7 |
| 48 | 27,740.50 | 1,647.87 | 5 | 6 |

All first-entry prices agree across official 1h, 15m and 1m bars. The independent rolling averages and bands match the native values. The later timing cases also expose floating-point equality differences at some additional signals. Close counts are native diagnostics. The priced exit ledger and original publication clock are unresolved, so the strategy stays pending with no performance rows. This rules out choosing a favorable release assumption after inspecting the results. [Binance historical archive and checksum format](https://github.com/binance/binance-public-data)

## Reproduction

1. Stage `source-4699.md` from FMZ archive commit `7853bb2bf262c4567ac238d3552d97f0e50cb801` in the existing offline AppContainer. Mirror the 24 dated pages listed in the JSON receipt section and retain the original observed snapshots for exact file hashes.
2. Run `python -m research.fmz_round53_4699_stage HOURLY_ARCHIVES QUARTER_HOURLY_ARCHIVES CBOE_HTML_DIRECTORY SANDBOX/4699-feed.json`.
3. Run `fmz_round53_4699_runner.py` inside the sandbox beside `replay_2864.py` and `probe_1216.py` to generate the timing controls.
4. Run `python -m research.fmz_round53_4699 SANDBOX MINUTE_ARCHIVES OUTPUT_JSON` to check the decision series and opening prints. The resulting evidence carries zero P&L rows.
