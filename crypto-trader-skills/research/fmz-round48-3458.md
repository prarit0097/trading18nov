# FMZ #3458 HP and volume-band replay

The exact archive uses one-hour BTC USD-M candles with a 15m base from 24 October to 23 November 2023 UTC, end exclusive. Its entry and exit rules combine a 100-observation Hodrick–Prescott filter, changes in OBV minus PVT, Bollinger ratios, and candle conditions. The visual stop and target calculations do not submit orders. Entries and exits use market reversals or `strategy.close_all`. ETH applies the same settings to a separate contract. [FMZ source](https://www.fmz.com/strategy/433080)

The literal Pine v4 run preserves the conditional `cancel` declaration. An equality control verifies the price comparison, while the inner `cancel` declaration shadows the outer variable. The outer Boolean stays false in the original. The exact direction and terminal-timestamp controls reproduce the literal ledger. The compatibility runtime's built-in EMA seeds with an SMA. The primary replay uses FMZ's documented first-value EMA for the two source calls and keeps the literal native seed as a sensitivity. [FMZ EMA reference](https://www.fmz.com/doc/9293#ta.ema)

Independent code verifies the HP solution, OBV, PVT, both Bollinger paths, all signal flags and the entire 100%-equity cash and position path for both seeds. All fill prices match the original public 15m and 1m opens. Two BTC 15m candles elsewhere differ from the minute reconstruction. The 15m files supply the price and volume inputs. The only 1m request reads the child timestamp, which remains complete, and the differing candles contain no fill price. [Binance public archive](https://github.com/binance/binance-public-data)

| Market | Closed | After-fee win rate | Gross P&L, USDT | After-fee P&L, USDT | After-fee drawdown, USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 16 | 62.50% | 91,403.31 | 66,230.76 | 45,174.89 |
| ETHUSDT | 16 | 68.75% | 144,378.52 | 118,436.99 | 90,719.65 |
| Pooled | 32 | 65.63% | 235,781.83 | 184,667.76 | 116,563.41 |

The strategy starts at the runtime's default 1 million USDT per contract with zero commission. The fee sensitivity applies 0.075% per side to the original calculated quantities and excludes funding. The table contains realized outcomes and omits one open position per market, separately marked in JSON. The literal native EMA closes 15 BTC trades for +73,566.60 USDT after fees. ETH's native-seed outcome matches the primary result.

## Reproduce

1. Put the pinned FMZ source in AppContainer scratch as `source-3458.md`. Obtain the eight official data archives from the report.
2. Run `python -m research.fmz_round48_3458_stage FIFTEEN_MINUTE_ARCHIVES MINUTE_ARCHIVES APP_CONTAINER_ROOT`.
3. Copy `fmz_round48_3458_runner.py` and `fmz_round48_3458_comparator.py` into the pinned AppContainer with its `replay_2864` and `probe_1216` support. Use a 240-second allowance for the source runner and preserve the isolation receipt.
4. Run `python -m research.fmz_round48_3458 APP_CONTAINER_ROOT OUTPUT_JSON`. Repeated finalization yields identical bytes.
