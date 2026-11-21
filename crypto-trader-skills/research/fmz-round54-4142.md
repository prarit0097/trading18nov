# FMZ #4142 multi-level daily order replay

The archived Pine v5 strategy sizes successive entries in fixed units, allows up to ten same-side entries, and combines rolling high/low pivots, Fibonacci levels, RSI, and MACD. It generates market entries, reversals and named short exits at future daily opens. The benchmark verifies 1,755 consecutive Binance USD-M daily candles per market. BTCUSDT is the archived contract. ETHUSDT supplies the same-window comparison. [Saved FMZ strategy](https://www.fmz.com/strategy/469612)

| Market | Closed lots | Gross win rate | After-fee win rate | Gross P&L | After-fee P&L | After-fee drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 18 | 55.56% | 55.56% | 25,347.39 | 21,062.63 | 28,752.26 |
| ETHUSDT | 20 | 40.00% | 40.00% | 17,815.78 | 17,561.92 | 3,475.72 |
| Pooled closed-lot sequence | 38 | 47.37% | 47.37% | 43,163.17 | 38,624.55 | 30,107.76 |

Amounts are in USDT. The common comparison fee is 0.075% per side. Drawdown uses settled lots, which remain separate when a reversal closes several pyramided entries together. Both cases finish flat. Funding, slippage, live broker fills and intratrade drawdown are outside this comparison. Every scored fill is a recorded Binance daily opening price.

The archived `08:00` browser-local endpoints become December 23, 2019 through October 11, 2024 inclusive on a UTC daily chart when interpreted in Asia/Shanghai. A second control interprets those saved endpoints in UTC and begins on the first complete UTC daily candle. Omitting that first bar changes the literal engine's ETH close count from 7 to 8. After the deviation check below, both timestamp interpretations produce the same actual orders, quantities, prices and closed-lot cashflows. [FMZ browser-local saved timestamps](https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving)

The literal engine requests eleven unused five-minute Fibonacci expressions. Supplying actual sourced five-minute bars or eliminating those eleven dead declarations yields identical behavior. The two unused conditional RSI crossover expressions are also inert. The portable benchmark retains all active rules. Earliest December 2019 daily candles came from the public Binance USD-M kline endpoint because the bulk monthly archive for that month was absent. [Binance USD-M klines](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)

The archived pivot predicate needs the deviation of fourteen successive extrema to equal zero. The pinned literal engine sometimes returns values such as `3.64 × 10⁻¹²` even when all fourteen values are exactly 10,540.00. There were 80 such constant-window deviations across the two BTC series and 72 across the two ETH series. The benchmark uses equality of the window's minimum and maximum, which is mathematically equivalent to zero absolute deviation, with the initial missing-value behavior preserved. The original native results remain a diagnostic. Independent calculations match every active source condition and all 69 market orders after the correction, including repeated entry IDs, named short closes, same-price FIFO groups, and all daily ledger values. Both SMA-seeded and first-value-seeded EMA controls give identical orders. [Pine strategy exits and pyramiding](https://www.tradingview.com/pine-script-docs/concepts/strategies/)

## Reproduction

1. Stage `source-4142.md` from FMZ catalogue commit `7853bb2bf262c4567ac238d3552d97f0e50cb801` in the existing offline AppContainer. The JSON includes source, engine, and market input checksums.
2. Put the exact nine Decimal-compatible public Binance `fapi/v1/klines` rows per symbol in `SANDBOX/4142-binance-dec2019.json`, keyed by market. Run `python -m research.fmz_round54_4142_stage SANDBOX MINUTE_ARCHIVES DAILY_ARCHIVE_DIRECTORY [MORE_DAILY_DIRECTORIES ...]` with the official monthly zips and receipts.
3. Run `fmz_round54_4142_runner.py` inside the offline sandbox alongside `replay_2864.py` and `probe_1216.py` to collect both saved-clock diagnostics and the portable zero-deviation controls.
4. Run `python -m research.fmz_round54_4142 SANDBOX OUTPUT_JSON`. Compare bytewise to `fmz-round54-4142.json` after independent signal, chronology, fee, and FIFO checks.
