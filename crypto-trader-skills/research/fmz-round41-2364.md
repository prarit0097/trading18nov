# FMZ #2364 Bat MACD archived replay

The pinned strategy uses a daily Binance USD-M BTC chart with a 1h base from 5 January 2023 through 11 January 2024, end exclusive. Its executable code combines chart MACD, 6h MACD, a stop series, relative vigor and volume-derived CCI. The three long-entry branches all size from 10,000 USDT divided by the decision candle close. Exits are market closes when the daily delta or closing price crosses its threshold. ETH reuses the same archived settings for a second contract. [FMZ source](https://www.fmz.com/strategy/438502)

The exact archive declares Pine v3 while using later request and ticker names. The portable replay substitutes the corresponding legacy `security` and `tickerid` vocabulary. A v4 header control and a separate explicit `A != 0` control produce identical output. Flattening the nested request changes 363 six-hour signal values in each market and one ETH entry predicate. Every broker order, position and equity mark still agrees. Three historical prefixes of 90, 220 and 365 days reproduce the full run through their respective endpoints. These controls cover the recorded path and do not establish equivalence of the nested expression in other market windows. [Pine v4 ticker migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-4/) [TradingView nested requests](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#nested-requests)

The run reconstructs 371 daily candles and 1,484 six-hour candles per market from authenticated Binance hourly inputs. An independent order and cash simulation matches all 42 fills, the signal-close unit rounding, the first hourly open on every fill day and all daily equity marks. Source commission is zero. The fee sensitivity deducts 0.075% per side for the same fills and excludes funding. The table reports realized P&L and realized drawdown. Each market ends with one open position, separately marked in the evidence. [Binance public archive](https://github.com/binance/binance-public-data)

| Market | Closed | After-fee win rate | Gross P&L, USDT | After-fee P&L, USDT | After-fee drawdown, USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 8 | 62.50% | 4,333.84 | 4,210.76 | 1,247.11 |
| ETHUSDT | 12 | 41.67% | 2,627.96 | 2,446.00 | 1,426.17 |
| Pooled | 20 | 50.00% | 6,961.79 | 6,656.76 | 2,023.16 |

## Reproduce

1. Place the checksum-pinned FMZ source in AppContainer scratch as `source-2364.md`. Use the 26 checksum-pinned Binance hourly archives from the report.
2. Run `python -m research.fmz_round41_2364_stage HOURLY_ARCHIVES APP_CONTAINER_ROOT` from the project.
3. Copy `fmz_round41_2364_runner.py` into the established AppContainer fixture directory with pinned Pine Compat and existing `probe_1216` and `replay_2864` support. Run it under the isolated launcher and retain its isolation receipt.
4. Run `python -m research.fmz_round41_2364 APP_CONTAINER_ROOT OUTPUT_JSON`. Repeat to confirm the same output bytes.
