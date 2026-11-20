# FMZ #4016 Hodrick–Prescott warm-up and bracket replay

The archive saves one day on a 1h Binance BTC USD-M chart, 17 February 2024 UTC. Its default Hodrick–Prescott filter solves a 100-observation system. A long is considered when the filtered source crosses above OHLC4. The strategy commits an ATR stop and 1:1 target at that signal. It sizes against 100% of equity. ETH applies the same rules and dates as a second historical contract. [FMZ source](https://www.fmz.com/strategy/442093)

The exact saved-day run has 24 candles, so neither instrument initializes the filter or produces an order. Explicitly guarding the filter's lookback and using the named direction alias produce identical results. A separate six-day control initializes the filter at index 99. The reported comparison uses 120 earlier hours solely to initialize indicators, with an explicit entry gate before the archived day's start. It begins the scored day flat with the source's default simulated equity. The Pine source formulas remain active after the gate.

An independent banded Cholesky solve matches each populated filter value. The archived lower-timeframe timestamp selects the last minute in each historical hour. The independent sizing model and minute bracket walk match three market entries and three same-day exits on the venue tick grid. The long bracket becomes eligible after the first position-aware hourly calculation. There is no first-touch minute with both exit levels crossing. [TradingView lower-timeframe requests](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lower-timeframes) [Binance public archive](https://github.com/binance/binance-public-data)

| Market | Closed with prehistory | After-fee win rate | Gross P&L, USDT | After-fee P&L, USDT | After-fee drawdown, USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 1 | 0% | -8,481.75 | -9,975.38 | 9,975.38 |
| ETHUSDT | 2 | 50% | -1,475.42 | -4,458.97 | 11,718.54 |
| Pooled | 3 | 33.33% | -9,957.18 | -14,434.35 | 21,693.92 |

The archived code sets no commission. The after-fee sensitivity uses 0.075% per side on the verified source sizes and excludes funding. Both markets finish flat. The exact cold day has zero P&L and drawdown and undefined win rate. The separate cold-start workbook rows retain these results alongside the initialized performance rows.

## Reproduce

1. Put the pinned FMZ archive in AppContainer scratch as `source-4016.md`. Use the four official, checksummed Binance archives listed in the report.
2. Run `python -m research.fmz_round47_4016_stage FIFTEEN_MINUTE_ARCHIVES MINUTE_ARCHIVES APP_CONTAINER_ROOT`.
3. Copy `fmz_round47_4016_runner.py` to the existing isolated runtime with `replay_2864` and `probe_1216` support. Run under AppContainer and retain its isolation receipt.
4. Run `python -m research.fmz_round47_4016 APP_CONTAINER_ROOT OUTPUT_JSON`. Repeated finalization produces identical bytes.
