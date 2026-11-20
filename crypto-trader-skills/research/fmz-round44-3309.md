# FMZ #3309 Delta RSI polynomial replay

The archived Pine v4 strategy fits a cubic to 50 observations of a 21-period RSI. It evaluates the derivative at the newest observation and crosses that derivative against a 9-period EMA. On the saved BTC USD-M 1h chart from 4 to 11 January 2024, end exclusive, the source defaults allow both directions and disable the optional filters and price brackets. ETH reuses the same settings on a second contract. [FMZ source](https://www.fmz.com/strategy/438479)

Two local scalar typing variants make the archived missing-value branch compile and return identical results. The Pine Compat EMA waits for nine defined values. FMZ's published EMA recurrence seeds with the first defined value, so the replay implements that recurrence explicitly and retains the native seed as a sensitivity. The source's two identical end predicates stay in place. Removing the disabled brackets changes no observable output. The two seeding rules change order timing and count on these inputs. [FMZ Pine reference](https://www.fmz.com/doc/9293#ta.ema)

An independent scaled least-squares calculation matches every ready original RSI window, derivative, normalized fit error and signal. All 25 market orders reconcile against the first open of the underlying checksummed 15m candle. The broker's gross P&L and all hourly equity marks reconcile with the independent ledger. The comparison deducts 0.075% per side from the settled round trips and excludes funding. Each market retains one separately marked open position. [Binance public archive](https://github.com/binance/binance-public-data)

| Market | Closed | After-fee win rate | Gross P&L, USDT | After-fee P&L, USDT | After-fee drawdown, USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 8 | 12.50% | 406.20 | -133.27 | 2,148.13 |
| ETHUSDT | 7 | 57.14% | 253.67 | 229.96 | 32.22 |
| Pooled | 15 | 33.33% | 659.87 | 96.69 | 2,148.13 |

Under the Pine Compat SMA-seeded sensitivity, the same period closes six positions on each instrument. BTC and ETH net -50.56 and +240.81 USDT. The catalogue rows above use the FMZ-documented initialization.

## Reproduce

1. Use the archive document pinned by the report as `source-3309.md` in AppContainer scratch. Use the two checksummed January 2024 USD-M 15m archives.
2. Run `python -m research.fmz_round44_3309_stage FIFTEEN_MINUTE_ARCHIVES APP_CONTAINER_ROOT`.
3. Copy `fmz_round44_3309_runner.py` into the pinned Python AppContainer runtime with `replay_2864` and `probe_1216` support. Use the isolated launcher with a 240-second allowance for the repeated matrix calculations. Preserve the isolation receipt.
4. Run `python -m research.fmz_round44_3309 APP_CONTAINER_ROOT OUTPUT_JSON` from the project directory. A second finalization yields the same file hash.
