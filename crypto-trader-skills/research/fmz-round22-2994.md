# FMZ #2994 WaveTrend cash-sized replay

The archived script compares a 12-period EMA of the WaveTrend series
with its three-bar moving average. The original daily entry follows the
relative values of those lines. The market exit also checks the
source's confirmed fractal divergences. The saved Binance USD-M window
is 2023-01-09 through 2024-01-15 UTC exclusive. All BTC and ETH daily
signals and indicator values are derived from 17,808 hourly candles.
The replay starts with 10,000 USDT and uses 10,000 USDT of cash for
each new position, rounded down to the 0.001 base-asset quantity step.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%9F%BA%E4%BA%8E%E4%B9%96%E7%A6%BB%E7%8E%87%E6%8C%87%E6%A0%87%E4%BC%98%E5%8C%96%E7%9A%84%E6%B3%A2%E5%8A%A8%E8%B7%9F%E8%B8%AA%E7%AD%96%E7%95%A5WaveTrend-and-DER-Based-Swing-Trading-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/438943) · [Binance public market archives](https://data.binance.vision/)

Pine Compat executes the original v4 signal program using the real
intraday series and the Heikin-Ashi transform required for its plots.
The four legacy Heikin-Ashi lookahead calls trigger runtime notices.
Every trading flag and both WaveTrend lines match an independent
calculation from daily charts alone. Perturbing the auxiliary feeds
also leaves the observed trading series and broker output unchanged.

Piner 0.13.0 runs the archived market orders and cash settings with those
verified flags. Both backends agree with an independent broker ledger
on daily open prices, cash-sized quantities, 0.025% per-side source
fees, 132 closed lots and 742 daily equity marks. Every modeled opening
fill matches the first hourly candle of that UTC day. The separate cash
fixture uses a signal-bar close of 100 and next-open fill of 190.30.
Piner and the independent formula give 52.548 units at that fill.
Pine Compat selects 100 units using the older close. The difference
changes the recorded size of two ETH fills in the historical run.
[TradingView order size and fill settings](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/) · [Pinned Piner source project](https://github.com/heyphat/piner)

| Market | Closed | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 62 | 35.48% | 6,045.59 | 5,734.29 | 2,270.65 |
| ETHUSDT | 70 | 31.43% | −5,610.72 | −5,961.71 | 5,961.71 |
| Pooled | 132 | 33.33% | 434.87 | −227.43 | 4,475.06 |

The table uses closed positions and realized equity. The final marks
are 15,977.40 USDT for BTC and 4,650.14 USDT for ETH, each with one
unsettled position. The simulator uses Pine v4's omitted margin setting.
Spread, funding and additional slippage are outside this replay.

## Reproduce

Fetch the Binance 1-hour archives and checksum files listed in the
report. Put the pinned FMZ archive in `PyScratch/source-2994.md`.
Reuse the Round 11 pinned Pine Compat package and Python isolation
launcher. The separate Node isolation directory needs the Round 7
Piner 0.13.0 archive, extracted package and Node runner.
[Round 11 Pine Compat runtime](fmz-round11-magnifier-priced.md) · [Round 7 Piner runtime](fmz-round7-magnifier.md)

```powershell
python -m research.fmz_round22_2994_stage PublicInputs PyScratch
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round22_2994_probe.py PyScratch/replay_2994.py
Copy-Item research/fmz_round22_2994_cash_control.py PyScratch/broker_2994.py
Copy-Item research/fmz_round22_2994_runner.py PyScratch/verify_2994.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 90
PyScratch/sandbox.ps1 PyScratch broker_2994.py '' 90
PyScratch/sandbox.ps1 PyScratch replay_2994.py '' 150
Copy-Item PyScratch/source-2994.md,PyScratch/2994-replay.json,PyScratch/2994-BTCUSDT.json,PyScratch/2994-ETHUSDT.json NodeScratch
Copy-Item research/fmz_round22_2994_cash.mjs NodeScratch/replay_2994.mjs
NodeScratch/sandbox.ps1 NodeScratch replay_2994.mjs '' 90
Copy-Item NodeScratch/2994-piner.json PyScratch
PyScratch/sandbox.ps1 PyScratch verify_2994.py '.' 90
python -m research.fmz_round22_2994 PyScratch Report.json
```

[Verified fills, costs and source receipts](fmz-round22-2994.json)
