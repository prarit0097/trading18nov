# FMZ #5708 archived-source historical replay

The archived High-Low Breakout Trend Following Strategy uses a 1-hour chart,
22-hour extrema, a separate 14-hour confirmation window lagged by two bars,
and reversal market entries. Its initial equity is USD 100,000 per market,
with 100% percent-of-equity sizing and `calc_on_order_fills=true`. The archive
names Binance USD-M BTCUSDT. ETHUSDT is an independent cross-asset replay.
[Pinned source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E9%AB%98%E7%82%B9%E4%BD%8E%E7%82%B9%E7%AA%81%E7%A0%B4%E8%B6%8B%E5%8A%BF%E8%BF%BD%E8%B8%AA%E7%AD%96%E7%95%A5High-Low-Breakout-Trend-Following-Strategy.md) · [FMZ public article](https://www.fmz.com/lang/en/strategy/426597)

The exact archived Markdown hash is
`5ba5718671a7c169e75e826206af348f7b201c57903f1b392d7bb073e8966cdf`.
The conversion to Pine v5 replaces legacy input and plot forms, names the
implicit high and low series, and removes the Boolean-to-integer comparison.
It preserves both entry guards, the lagged extrema, the original strategy
parameters, absence of an exit command and the two plotted conditions. The
independent signal oracle checks every chart bar. The first 22 bars require
additional history for the lagged 22-bar extrema.
[TradingView legacy Boolean conversion](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-3/) · [TradingView namespaces](https://www.tradingview.com/pine-script-docs/en/v5/migration_guides/To_Pine_version_5.html/) · [TradingView extrema warmup](https://www.tradingview.com/pine-script-docs/language/execution-model/#time-series)

The replay retains the source's historical Pine order model. A synthetic
control fills a long at 130 and reverses at 132 during the same bar following
the callback. Turning the callback off in that control moves the reversal to
45 on the next hourly open. The broker and an independent oracle agree on all
54 actual fills, 50 closed lots and four ending open positions. None of the
actual replays triggers a same-bar reversal. A separate control turns on Pine
Bar Magnifier with the FMZ host setting of 15-minute base data. It uses 17,664
complete Binance-derived 15-minute observations and returns identical full
results for the four market runs. An omitted lower-timeframe group triggers
the expected fallback diagnostic only in the negative control.
[Legacy Pine historical scheduler](https://www.tradingview.com/pine-script-docs/v3/essential/strategies/) · [FMZ base-period configuration](https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving)

Pricing and sizing use the native Pine Compat runtime from Round 11, with a
0.001 lot step and USD conversion from the last completed UTC day's Coinbase
USDT-USD close. This selects a named public FX model. TradingView's conversion
provider may differ. The original strategy declares no Pine commission. The
cost comparison subtracts 0.075% per side on the same closed fills with each
fee translated at its own rate. This comparison holds sizing fixed. Earlier
projection of the costs into position sizing would produce a different ledger.
Drawdown tracks realized equity, with ending exposure recorded separately.
No funding or slippage is imposed by this replay.
[Coinbase candle documentation](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles) · [Binance public archive](https://data.binance.vision/)

| UTC sample | Contract | Closed | After-fee win rate | Gross USD | After-fee USD | After-fee drawdown USD |
|---|---|---:|---:|---:|---:|---:|
| August 2026 | BTCUSDT | 10 | 20.00% | 8,160.07 | 6,622.96 | 8,576.06 |
| August 2026 | ETHUSDT | 8 | 12.50% | 14,989.88 | 13,760.49 | 8,937.14 |
| September–October 2026 | BTCUSDT | 15 | 20.00% | -10,454.86 | -12,523.16 | 13,338.05 |
| September–October 2026 | ETHUSDT | 17 | 17.65% | -32,484.39 | -34,660.71 | 36,771.13 |

## Reproduce

Use the earlier AppContainer launcher and isolation probe in an independent
scratch directory. Place the supported Python copy, the pinned Round 11
runtime under `Scratch/priced-runtime`, the archived Markdown as
`Scratch/source-5708.md`, and the Coinbase FX response as
`Scratch/coinbase-usdt-usd-daily.json`. The FX period covers 2026-07-31 to
2026-11-01 and its first effective day is 2026-08-01. Keep the downloaded
archive and public market ZIPs outside tracked files. The Round 12 staging
checks Binance's published file hashes against Round 10 and verifies each
recomputed hourly feed before writing its independent 15-minute control.
[Round 11 runtime build](fmz-round11-magnifier-priced.md) · [Round 10 data sources](fmz-round10-magnifier-market.md) · [Coinbase FX response](https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2026-07-31T00%3A00%3A00Z&end=2026-11-01T00%3A00%3A00Z)

```powershell
python -m research.fmz_round10_magnifier_market stage Scratch PublicZips
python -m research.fmz_round12_5708_stage Scratch PublicZips research/fmz-round10-magnifier-market.json
Copy-Item research/fmz_round12_5708_controls.py Scratch/observe.py
Copy-Item research/fmz_round12_5708_runner.py Scratch/replay_5708.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch observe.py '' 90
Scratch/sandbox.ps1 Scratch replay_5708.py '' 240
python -m research.fmz_round12_5708 Scratch Report.json
```

[Verified report and metrics](fmz-round12-5708.json)
