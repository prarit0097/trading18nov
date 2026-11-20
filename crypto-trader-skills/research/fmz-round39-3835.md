# FMZ #3835 native BTC zero-order replay

The source combines a two-green Heikin-Ashi sequence, ordered moving averages and a rising smoothed stochastic into a long score. Its original daily BTC USD-M study runs from 8 December 2022 to 14 December 2023, end exclusive, with a 1h base. The bearish score is disabled by the archived default. Both entry calls explicitly floor 10% of the 50,000 starting capital divided by the close. [FMZ source](https://www.fmz.com/strategy/435481)

The original dotted assignment to `strategy.initial_capital` prevents a strict Pine v4 compilation. The tested compatibility variant moves the single literal 50,000 into the strategy declaration. A variant that additionally replaces the order-quantity denominator with the equivalent literal 5,000 produces identical outputs. Every source decision and order call remains in the declaration-only variant. [TradingView strategy sizing](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/#position-sizing)

BTC has 371 daily bars rebuilt from checksummed Binance USD-M 1h archives. The lowest candle price is 16,210.00 and the lowest close is 16,429.20, so the whole-unit order quantity is zero throughout. The independent Heikin-Ashi, moving-average, stochastic and score calculations match the runtime. The runtime's 200-bar EMA seeds from its first full SMA and admits 62 bullish bars. A first-value EMA seed admits 83 and still yields zero units. Even suppressing the entry stop leaves the BTC ledger flat. Gross and after-fee P&L and drawdown are zero. Win rate is undefined with zero closes. [Binance public archive](https://github.com/binance/binance-public-data)

The ETH diagnostic reaches two to four units and receives 46 nonfinite-stop errors while flat. Suppressing that parameter yields 38 closes and changes author behavior. ETH stays outside the performance rows until historical flat-stop execution is verified. The BTC-only result tests the saved instrument and does not resolve this ETH entry difference.

## Reproduce

1. Copy the source document from FMZ archive revision `7853bb2bf262c4567ac238d3552d97f0e50cb801` into AppContainer scratch as `source-3835.md`. The evidence JSON pins the document and every Binance archive.
2. Prepare replay inputs with `python -m research.fmz_round39_3835_stage HOURLY_ARCHIVES APP_CONTAINER_ROOT`.
3. Copy `fmz_round39_3835_runner.py` into the existing Windows AppContainer fixture directory with the pinned Pine Compat binary and the established `replay_2864`, `probe_1216` and `replay_2994` support. Execute it with the existing isolation launcher and preserve the no-file/no-network receipt.
4. Run `python -m research.fmz_round39_3835 APP_CONTAINER_ROOT OUTPUT_JSON`. The final checks independently reconstruct prices, eligibility factors, quantity and the complete flat BTC equity path.
