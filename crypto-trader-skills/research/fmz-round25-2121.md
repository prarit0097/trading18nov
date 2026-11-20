# FMZ #2121 dual SuperTrend replay

The source compares a daily SuperTrend with a second SuperTrend built
from the final confirmed two-hour candle in each daily period. An entry
requires the daily direction to flip and agree with the second series.
The order uses one base-asset unit and a 500-tick target with a 400-tick
stop. The saved Binance USD-M BTCUSDT window is 2022-11-20 to 2023-11-26
UTC exclusive. ETHUSDT uses the same dates and rules on its own book.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%8F%8C%E5%9D%87%E7%BA%BF%E9%9C%87%E8%8D%A1%E7%AA%81%E7%A0%B4%E7%AD%96%E7%95%A5Dual-Moving-Average-Oscillation-Breakthrough-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/433448)

The v4 source requires declarations for six recursive series, the v4
spelling of three request calls and explicit visual constants. Those
compatibility changes preserve the source equations. The normalized
v4 and chart-only v5 broker outputs match. Independent calculations
verify both recursive trend families and all trading flags on 742 daily
candles. The saved hourly execution feed and the targeted minute replay
also preserve those signals. Withholding a complete bar group triggers
the expected fallback warning.
[TradingView lower-timeframe requests](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lower-timeframes) · [TradingView Bar Magnifier](https://www.tradingview.com/pine-script-docs/concepts/strategies/#bar-magnifier)

There are 24 hours where both the stop and target are reached. For each
hour, 60 checksum-verified official minute records aggregate to the same
hourly open, high, low, close and volume. The first triggering minute
reaches one level or opens through it in every case. Those checks change
11 simulated exit prices from the hourly-only model. All 86 final trades
and the daily cash marks are independently reconciled. Price levels are
simulated fills backed by traded candle ranges. Historical executable
quotes and depth remain outside this replay.
[Binance futures market archive](https://github.com/binance/binance-public-data#futures)

| Market | Closed | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 43 | 46.51% | 260.00 | −1,434.16 | 1,434.16 |
| ETHUSDT | 43 | 39.53% | −19.00 | −126.93 | 130.19 |
| Pooled | 86 | 43.02% | 241.00 | −1,561.09 | 1,561.09 |

Both positions finish flat. The source's zero commission defines gross
P&L. The fee comparison uses 0.075% per side on the same fills, and
drawdown follows realized equity. The runtime's archived default
starting capital is 1,000,000 USDT per symbol.

## Reproduce

Download the listed public hourly and minute archives with their
checksums. Put the pinned FMZ archive at `Scratch/source-2121.md`.
Reuse the Round 11 Pine Compat application container.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round25_2121_stage PublicHours Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round25_2121_probe.py Scratch/replay_2121.py
Copy-Item research/fmz_round25_2121_runner.py Scratch/verify_2121.py
Copy-Item research/fmz_round25_2121_refine.py Scratch/refine_2121.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_2121.py '' 150
Scratch/sandbox.ps1 Scratch verify_2121.py '' 90
python -m research.fmz_round25_2121_minute_stage PublicMinutes Scratch
Scratch/sandbox.ps1 Scratch refine_2121.py '' 90
python -m research.fmz_round25_2121 Scratch Report.json
```

[Verified trades and 24 minute-data receipts](fmz-round25-2121.json)
