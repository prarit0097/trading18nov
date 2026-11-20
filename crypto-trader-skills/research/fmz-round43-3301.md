# FMZ #3301 daily RSI and two-hour MA replay

The saved BTC USD-M strategy uses a 2h chart and a 15m base from 4 November to 4 December 2023, end exclusive. Defaults trade long only, comparing the 50-bar and 100-bar chart SMAs. Both the chart and daily RSI use 20 periods and must pass the archived permissive range check. Extra conditions and the bracket toggles are off. The source starts with 100 USDT and requests 100% of equity per new entry. ETH applies the same settings on a different contract. [FMZ source](https://www.fmz.com/strategy/434288)

The strict compiler rejects the built-in RSI call because an unrelated string option has the identifier `rsi`. The compatibility variant renames that option and its exact references. A control that additionally removes the disabled bracket has the same orders, trades, equity and plots. No indicator formula, filter, time gate or active order is replaced.

Each market uses 2,880 checksummed 15m candles and independently reconstructs 360 two-hour and 30 daily candles. Both Wilder RSI series and all SMA and gate values agree with an independent calculation. The first usable daily RSI arrives only at the ending 2h candle of the twenty-first day. The cash model verifies all four next-open fills against the first 15m open, rounds to a 0.001 unit step and matches the equity series. [TradingView higher-timeframe data](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#higher-timeframes) [Binance public archives](https://github.com/binance/binance-public-data)

BTC has no realized exits and ETH closes one losing trade. ETH realizes -2.32992 USDT before fees and -2.47802 USDT after an assumed 0.075% per side. BTC win rate is undefined and the ETH closed win rate is 0%. Both contracts end open. Reinvesting cash net of the modeled fees leaves all accepted quantities unchanged in this specific sample. The open BTC and ETH lots have estimated net marks of +4.43027 and +3.97566 USDT if liquidated at the final candle close with the same costs. These marks remain separate from realized P&L and drawdown and use no funding or slippage.

## Reproduce

1. Copy the pinned source file to AppContainer scratch as `source-3301.md` and prepare the checksummed 15m archives in the JSON.
2. Run `python -m research.fmz_round43_3301_stage FIFTEEN_MINUTE_ARCHIVES APP_CONTAINER_ROOT`.
3. Copy `fmz_round43_3301_runner.py` into the existing isolated AppContainer fixture directory with the pinned Pine Compat and established `replay_2864` and `probe_1216` support. Execute it under the isolated launcher and preserve the isolation evidence.
4. Run `python -m research.fmz_round43_3301 APP_CONTAINER_ROOT OUTPUT_JSON`. The finalizer independently checks the source timeframe projection and both account paths.
