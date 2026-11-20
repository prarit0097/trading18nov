# FMZ #2708 Heikin-Ashi and CCI market-close replay

The exact Pine v4 source runs for its archived Binance USD-M BTCUSDT
period and the matching ETHUSDT comparison. Each market supplies 180
four-hour candles between January 6 and February 5, 2024 UTC exclusive.
The chart and half-hour requests are sourced from 2,880 official
15-minute candles per market. The Heikin-Ashi recurrence starts with the
first source-window candle, and standard market opens supply the
execution prices.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%9F%BA%E4%BA%8EHeikin-Ashi%E7%9A%84%E8%B6%85%E7%BA%A7%E8%B6%8B%E5%8A%BF-trailing-stop%E6%8D%9F%E7%AD%96%E7%95%A5SuperTrend-Trailing-Stop-Strategy-Based-on-Heikin-Ashi.md) · [FMZ source page](https://www.fmz.com/strategy/441178)

The independent calculation reproduces the Heikin-Ashi OHLC, recursive
SuperTrend, CCI trail, EMA/HMA and RSI filters at every decision. The
default higher-timeframe argument is the chart's own 240-minute
interval. Its explicit history offset uses the previous confirmed CCI
trail. Both compatibility warnings refer to these offset requests.
The 30-minute Heikin-Ashi close is present in the source but has no
active order dependency. The unused built-in SuperTrend output can
also be removed with identical trading series and fills.
[TradingView higher-timeframe history behavior](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lookahead)

The source submits entries from the Heikin-Ashi and trend rules.
A CCI trail crossover or the daily exit flag submits a market close.
The saved hour and minute inputs first satisfy the session condition
at 16:00 UTC on the four-hour grid. These closes become eligible at
20:00 UTC. The audit matches every modeled open and close to the
first 15-minute candle of its four-hour bar. It also reconstructs every
equity mark. All 15 positions close in the window.

| Market | Closed | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 7 | 42.86% | −151.80 | −606.38 | 2,092.41 |
| ETHUSDT | 8 | 37.50% | 68.20 | 39.46 | 129.20 |
| Pooled | 15 | 40.00% | −83.60 | −566.92 | 2,146.79 |

One base unit per order and 1,000,000 USDT per market are the Pine v4
defaults used by this archive. The source declares neither commission
nor slippage. The after-fee comparison adds a 0.075% fee per side
to the same closed positions. Drawdown uses realized equity. Funding,
spread and order-book execution are outside the modeled benchmark.

## Reproduce

Use the two January and February Binance 15-minute market archives and
sidecars listed in the report. Save the pinned script as
`PyScratch/source-2708.md` and reuse the Round 11 native runtime and its
isolation launcher.
[Round 11 isolated Pine Compat](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round33_2708_stage Public15Min PyScratch
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round22_2994_probe.py PyScratch/replay_2994.py
Copy-Item research/fmz_round33_2708_runner.py PyScratch/probe_2708.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 45
PyScratch/sandbox.ps1 PyScratch probe_2708.py '' 90
python -m research.fmz_round33_2708 PyScratch Report.json
```

[Verified indicators, fills and metrics](fmz-round33-2708.json)
