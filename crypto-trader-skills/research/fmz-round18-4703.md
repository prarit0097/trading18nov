# FMZ #4703 archived daily pivot replay

The archived Pine v4 script uses Binance USD-M BTCUSDT on a daily chart.
Its default pivot is the mean of the previous day's high, low and close.
A candle opening below that pivot and closing above it submits a long
entry for one base-asset unit. The next daily opening fills the order.
The default stop distance is the prior close times 0.5 in ticks. The
independent ETHUSDT run uses the same inputs and rules.
[Pinned source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E6%97%A5%E5%86%85%E4%BA%A4%E6%98%93%E5%85%B3%E9%94%AE%E7%82%B9%E7%AD%96%E7%95%A5Intraday-Pivot-Points-Trading-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/434581)

The saved 2022-11-30 to 2023-12-06 wall times are interpreted as UTC.
The replay fixes the native display clock at the saved end. Each daily
bar opens at 00:00 UTC, so the entry rule's hour limit is satisfied and
the hour-15 close remains inactive. An independent calculation checks
the source's same-chart requests and proves all prior-day prices lag
the current bar, addressing the generic lookahead warnings. A guard
control skips the first bar's two unavailable stop values and returns
the same historical trades, positions, orders and equity.
[TradingView same-context requests](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/) · [FMZ saved settings](https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving)

The two runs use 742 fully closed daily bars, and 740 have prior-day
inputs. Official one-hour records on all 14 execution days aggregate
to the same daily candles and reproduce all 24 order fill prices.
There are 11 settled trades and one ending open position per market.
The archive's zero-fee run defines gross P&L. The comparison applies
0.075% per side to the same settlements, and drawdown uses realized
equity in USDT.
[Binance futures kline API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)

| Market | Closed trades | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|
| BTCUSDT | 1 | -838.40 | -863.40 | 863.40 |
| ETHUSDT | 10 | -61.47 | -80.18 | 80.18 |
| Pooled | 11 | -899.87 | -943.57 | 943.57 |

## Reproduce

Reuse the Round 16 daily data envelopes and the pinned Round 11 runtime
with the AppContainer Python launcher. The saved date slice is read from
`Scratch/5411-feed-BTCUSDT.json` and `Scratch/5411-feed-ETHUSDT.json`.
Place the pinned script archive in `Scratch/source-4703.md`. The offset
to the next daily opening and the stop's tick rounding are verified
against each fill in the offline replay. The base-fetch command checks the
hourly public responses before the independent offline ledger audit.
[Daily data preparation](fmz-round16-5411.md) · [Pine Compat runtime](fmz-round11-magnifier-priced.md)

```powershell
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_4703_probe.py Scratch/probe_4703.py
Copy-Item research/fmz_round18_4703_runner.py Scratch/verify_4703.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch probe_4703.py '' 120
python -m research.fmz_round18_4703_base Scratch Scratch
Scratch/sandbox.ps1 Scratch verify_4703.py '' 120
python -m research.fmz_round18_4703 Scratch Report.json
```

[Verified results and quote manifest](fmz-round18-4703.json)
