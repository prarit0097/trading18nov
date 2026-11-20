# FMZ #4026 legacy RSI and minute bracket replay

The archive saves a Binance BTC USD-M contract on a 3h chart with a 15m base in December 2023. The executable default entering rules cross the requested 1m RSI above 35 for longs or below 65 for shorts. The 15m RSI and lower moving averages are also calculated. The default brackets use a 100-tick stop and a 1,500-tick target, with the trailing arguments disabled. ETH applies the same rules on separate venue data. [FMZ source](https://www.fmz.com/strategy/438929)

The strict source mixes Pine v2 with newer display, time and request names. The compatible v2 replay uses the legacy request and symbol forms, removes an unused timestamp expression and omits two unsupported plot-size arguments. Explicit named entry-direction aliases and omission of the alert-only appendix independently preserve the broker and indicator traces. The runtime emits seven expected legacy-lookahead warnings. For these lower-timeframe requests the historical rule selects the first child. The independent Wilder calculation matches every 1m and 15m RSI observation. Choosing the last intrabar instead changes signals on both pairs. [TradingView lower-timeframe merge behavior](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lower-timeframes)

Checksummed Binance archives supply 44,640 minute bars, 2,976 fifteen-minute bars and 248 source candles per market. The independent bracket walk locates all 57 entry opens and the first eligible stop or target in each source candle. No first-touch minute reaches both thresholds. In two BTC cases the minute chronology reaches a stop before the target assigned by chart-only emulation. The 11 December 03:00 UTC short exits at 41,972.30, and the 26 December 12:00 UTC long exits at 42,710.00. The workbook uses the minute replay. Both markets end flat. [Binance public archive](https://github.com/binance/binance-public-data)

| Market | Closed | After-fee win rate | Gross P&L, USDT | After-fee P&L, USDT | After-fee drawdown, USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 31 | 3.23% | -150.00 | -2,106.44 | 2,106.44 |
| ETHUSDT | 26 | 3.85% | -10.00 | -97.62 | 97.62 |
| Pooled | 57 | 3.51% | -160.00 | -2,204.06 | 2,204.06 |

The source sets no commission. The after-fee column uses 0.075% on each side, with no funding, queue priority or additional slippage modeled. All rows are historical simulations.

## Reproduce

1. Copy the archive document pinned in the report into Windows AppContainer scratch as `source-4026.md`. Obtain the four checksummed official December 2023 USD-M archives identified in the evidence.
2. Run `python -m research.fmz_round46_4026_stage FIFTEEN_MINUTE_ARCHIVES MINUTE_ARCHIVES APP_CONTAINER_ROOT`.
3. Copy `fmz_round46_4026_runner.py` into the pinned AppContainer runtime with `replay_2864` and `probe_1216` fixture support. Use the isolated runner with a 240-second allowance and retain the isolation receipt.
4. Run `python -m research.fmz_round46_4026 APP_CONTAINER_ROOT OUTPUT_JSON`. Repeating the finalizer yields identical bytes.
