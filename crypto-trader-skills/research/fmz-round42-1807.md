# FMZ #1807 momentum strategy archived replay

The source saves BTC USD-M on a 1h chart from 18 through 23 November 2023, end exclusive, with a 15m base. Its effective defaults combine 2-period RSI below 12 and 12-period stochastic K below 10. The apparent Bollinger toggle has no effect because the executable condition uses the disabled StochRSI switch. Exits use a 1% high-water target, a 2% low stop or the opposite EMA signal. The trailing switch is off, and the body submits only long orders. ETH uses the same formula over the saved dates. [FMZ source](https://www.fmz.com/strategy/435880)

The compatibility variant restores the older request, ticker and period vocabulary, renames a series that shadows the built-in RSI, expresses the long and short Boolean comparisons explicitly and gives the source's constant zero short exit a series type. The exact eager `iff` calls stay in Pine v3. Removing the trailing plot-only appendix in a control and expressing the Boolean predicates as explicit 1/0 comparisons in a second control yield identical runtime traces. [TradingView Pine migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)

An independent RSI, stochastic, EMA and trade-state calculation verifies every entry, target and stop flag. The first-value EMA seed control preserves the entry and exit decisions. Four verified Binance archives supply the 15m chart base and actual 1m candles for 3m and 5m requests. On both markets, all eight market fills match the first 15m open after the corresponding decision. Threshold touches generate market-close instructions, and the simulated fill executes at the next chart open. [Binance public archive](https://github.com/binance/binance-public-data)

Source commission is zero. The after-fee sensitivity applies 0.075% per side and excludes funding. Each market closes two trades and ends flat.

| Market | Closed | After-fee win rate | Gross P&L, USDT | After-fee P&L, USDT | After-fee drawdown, USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 2 | 50% | 321.60 | 212.21 | 106.80 |
| ETHUSDT | 2 | 50% | 6.72 | 0.81 | 19.07 |
| Pooled | 4 | 50% | 328.32 | 213.02 | 125.87 |

## Reproduce

1. Place the archive document pinned in the JSON in scratch as `source-1807.md`. Fetch only the two 15m and two 1m Binance files identified by their checksums.
2. Run `python -m research.fmz_round42_1807_stage FIFTEEN_MINUTE_ARCHIVES MINUTE_ARCHIVES APP_CONTAINER_ROOT`.
3. Copy `fmz_round42_1807_runner.py` to the established fixture directory with the pinned Pine Compat binary and `replay_2864` and `probe_1216` support. Execute under AppContainer and retain its isolation receipt.
4. Run `python -m research.fmz_round42_1807 APP_CONTAINER_ROOT OUTPUT_JSON`. The independent ledger and output hashes are deterministic.
