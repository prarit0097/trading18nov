# FMZ #4881 Vortex and legacy RSI replay

This benchmark reproduces 720 hourly candles per market from August 19 to September 18, 2023 UTC exclusive. The archived contract is BTCUSDT on Binance USD-M. ETHUSDT supplies a same-period comparison. The source uses 14-period Vortex crossings and hourly range filters with a fixed 20,000 cash order, plus a reversed-argument legacy RSI call and capital-based exits. [Archived FMZ strategy](https://www.fmz.com/strategy/427311)

| Market | Closed trades | Gross win rate | After-fee win rate | Gross P&L | After-fee P&L | After-fee drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 17 | 35.29% | 23.53% | 988.45 | −712.91 | 989.97 |
| ETHUSDT | 8 | 25.00% | 0.00% | −1,731.89 | −2,527.53 | 2,527.53 |
| Pooled closed-trade sequence | 25 | 32.00% | 16.00% | −743.44 | −3,240.45 | 3,240.45 |

Amounts are in USDT with the declared commission of 0.25% per side. There are zero open positions at the historical cutoff. Drawdown uses the closed-trade sequence. Funding, spread, slippage, venue margin enforcement and live FMZ behavior are outside the benchmark.

## Capital and RSI compatibility

The saved declaration starts the wallet at 20,000. A later assignment tries to write 50,000 to the read-only Pine capital field used by the risk thresholds. The literal source fails compilation. Three explicit controls use 20,000 for both wallet and thresholds, 50,000 for both, and 20,000 for wallet with thresholds based on the attempted 50,000 value. The controls give identical historical order times, prices, quantities and realized USDT outcomes. With starting capital of 20,000 or 50,000, the same series gives BTC drawdown of 4.88% or 1.97% and ETH drawdown of 12.64% or 5.06%, respectively. The report normalizes the workbook percentages to the declared 20,000 starting capital. This invariance is specific to the archived interval. [FMZ source](https://www.fmz.com/strategy/427311)

The independent replay verifies the deprecated numeric-series RSI ratio under the literal argument order `rsi(m,totalprice)`. It never crosses 70 in the saved period. The 7% loss and 16% target controls are also inactive. On both markets every held quarter-hour high and low stays between the tighter 20,000-based thresholds of −1,400 and +3,200 USDT. The largest adverse and favorable values are −769.53 and +1,562.13 in BTC, and −1,393.24 and +720.78 in ETH. Official minute bars independently confirm all four extrema. The ETH adverse bound leaves only 6.76 USDT of headroom against the tighter threshold. [TradingView Pine v4 RSI overload](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#removed-an-rsi-overload)

## Callback chronology

One native BTC exit callback used an hourly close that had yet to occur. At the 12:00 UTC August 31 opening fill, the observed price was 27,291.80 and the previous hour's low was 27,190.30. The source's `close <= prior_low` predicate could only become true after that opening callback. The independently reconstructed historical exit uses the confirmed 12:00 hourly signal and the 13:00 opening price of 27,178.80. Official minute bars verify both opening prints and reconstruct the intervening hour. Independent evaluation found no newly executable order at any actual opening fill callback. Every other date, order and fill agrees with the native comparison. [TradingView calculation after order fills](https://www.tradingview.com/pine-script-docs/concepts/strategies/#calc_on_order_fills)

Every scored fill matches the relevant official next hourly opening and its first quarter-hour opening. Fixed-cash lot size is evaluated using the signal candle's confirmed close, while the fill uses the next open. This distinction changes one order from 12.153 ETH to the native 12.154 ETH. The benchmark covers historical evaluation at confirmed hourly bars and at fills. It does not emulate decisions on unrecorded live ticks. [Binance Public Data](https://github.com/binance/binance-public-data)

## Reproduction

1. Pin the FMZ catalogue to `7853bb2bf262c4567ac238d3552d97f0e50cb801`. Stage the verified source and Pine runtime in the existing Windows AppContainer. The JSON records the source and engine hashes.
2. Run `python -m research.fmz_round51_4881_stage HOURLY_ARCHIVES QUARTER_HOURLY_ARCHIVES SANDBOX/4881-feed.json`. Supply official Binance monthly zip archives and `.CHECKSUM` receipts. The staging independently reconciles the complete quarter-hour archive with the hourly OHLC.
3. Run `fmz_round51_4881_runner.py` inside the sandbox beside `replay_2864.py` and `probe_1216.py`. It records the literal failure, migration controls, and historical full-bar callback and confirmed-only native control ledgers.
4. Put the verified August 23 ETH and August 29 and 31 BTC daily minute zips next to the sandbox folder. Run `python -m research.fmz_round51_4881 SANDBOX MONTHLY_MINUTE_ARCHIVES OUTPUT_JSON`. The finalizer recalculates source signals, opening callbacks, whole lots, cash P&L, alternate-capital drawdown and minute extrema before writing the report.
