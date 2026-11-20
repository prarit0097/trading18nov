# FMZ #3366 combined trailing-bracket evidence

The exact Pine v5 source uses a 15-day Bollinger breakout filtered by its default volatility condition. It attaches a 2% fixed stop, 9% target and a trailing rule with 2% activation and 0.5% offset. The trend and ROC toggles are off, and the apparent maximum-intraday-loss command is commented. BTC USD-M is the archived instrument. ETH checks the same source on a second contract. [FMZ source](https://www.fmz.com/strategy/433024)

The replay keeps the 347 complete daily bars from 22 November 2022 through 4 November 2023 UTC, end exclusive, excluding the archive's last partially elapsed day. The daily chart is built from verified official 1h candles. An independent population-standard-deviation calculation matches every entry and opposite-close predicate. Removing the display-only monthly table leaves the observed results identical. The daily broker reports 13 BTC and nine ETH closes. Those counts describe the emulator traces. [Binance public archive](https://github.com/binance/binance-public-data)

For selected episodes, the diagnostic replays the source trail from the entry-day bracket and introduces the fixed stop and target after the first position-aware daily decision. The October BTC 1m archives exactly match their parent 1h OHLC.

| BTC entry date | Daily emulator exit | First eligible source trail under the finer-price diagnostic |
|---|---:|---:|
| 2023-06-21 | 30,680.50 | 28,945.10 in the 01:00 UTC hourly bar |
| 2023-10-24 | 35,134.60 | 33,584.60 in the 00:59 UTC minute |

Both OHLC path controls agree for these episodes. The finer-price events verify the historical trigger opportunities. They do not provide order-book priority or authenticated fills. The January native target at 18,997.392 also falls off the BTC price grid. The catalogue keeps one Pending disposition without a win rate, P&L or drawdown. A full execution replay still needs to verify order amendments, day-to-day trailing state and any ambiguous child-bar timeline. [TradingView trailing stops and historical broker behavior](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/#trailing-stops)

## Reproduce

1. Place the report's checksum-pinned archive in AppContainer scratch as `source-3366.md`. Fetch the 26 hourly and two October minute archives identified in the JSON.
2. Run `python -m research.fmz_round45_3366_stage HOURLY_ARCHIVES APP_CONTAINER_ROOT`, then `python -m research.fmz_round45_3366_witness MINUTE_ARCHIVES APP_CONTAINER_ROOT`.
3. Run `fmz_round45_3366_runner.py` under the pinned Python AppContainer with `replay_2864` and `probe_1216` support. Preserve the isolation receipt.
4. Run `python -m research.fmz_round45_3366 APP_CONTAINER_ROOT OUTPUT_JSON`. Repeating the finalizer yields identical output.
