# FMZ #1073 restored WaveTrend replay

The archive preserves the `strategy` definition as a commented line.
Removing its leading two slash characters restores all original settings,
including 10,000 USDT initial capital and cash sizing and a 0.025% fee
per side. The resulting Pine v4 program is byte-identical to the active
program verified for FMZ #2994. This archive sets a different market
window and period. It saves BTCUSDT from 2022-04-16 at 00:00 to
2022-05-15 at 23:59 UTC, using a 2-hour chart and 15-minute base.
ETHUSDT is a separately funded comparison.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/VuManChu-Cipher-B-Divergences-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/363822) · [Same active program](fmz-round22-2994.md)

The final quarter-hour is built from the 14 actual minute candles
complete at the 23:59 cutoff. The additional minute opening at 23:59
is excluded. On each market one official 22:30 quarter on 2022-05-01
has zero recorded trades. The marks preserve that observation. Every
modeled execution uses the first 15-minute candle of its 2-hour group,
which has positive trading volume in all cases.
[Binance public archive definitions](https://github.com/binance/binance-public-data#futures)

The independent calculation matches both WaveTrend curves and all four
order flags on 720 chart bars. The alternate Piner JavaScript and
interpreter broker modes independently match the next-open settlement
of 123 closed lots, 248 market events and 720 chart equity marks. The
cash order uses the execution price with a 0.001-unit step. The
previous-close cash quantity used by the signal runtime changes four
ETH entry sizes. The fee results use the archived execution-price
cash amount and fee setting.
[TradingView cash order and execution properties](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/)

| Market | Closed | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 56 | 41.07% | 4,419.77 | 4,140.90 | 740.40 |
| ETHUSDT | 67 | 35.82% | 2,536.15 | 2,202.02 | 1,195.37 |
| Pooled | 123 | 38.21% | 6,955.92 | 6,342.92 | 1,758.84 |

Drawdown and win rate use closed lots. One position remains open in each
book. The terminal marked equities are 14,490.55 USDT for BTC and
12,736.59 USDT for ETH. The exact source's auxiliary Heikin-Ashi
lookahead warnings are retained. The independent order flags rely on
the traded 2-hour data only. Spread, funding and additional slippage
are outside this historical model.

## Reproduce

Download the Binance 15-minute monthly and terminal-day 1-minute archives
with their checksums from the report. Put the pinned FMZ archive in
`PyScratch/source-1073.md`. Reuse the Round 22 pinned Pine Compat and
Piner isolation directories. The generated Node runner is built from
the pinned Round 22 script with the #1073 market alias and timeframe.
[Round 22 runtime prerequisites](fmz-round22-2994.md)

```powershell
python -m research.fmz_round24_1073_stage Public15m Public1m PyScratch
python -m research.fmz_round24_1073_prepare_broker research/fmz_round22_2994_cash.mjs NodeScratch/replay_1073.mjs
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round22_2994_probe.py PyScratch/replay_2994.py
Copy-Item research/fmz_round22_2994_runner.py PyScratch/verify_2994.py
Copy-Item research/fmz_round24_1073_probe.py PyScratch/replay_1073.py
Copy-Item research/fmz_round24_1073_runner.py PyScratch/verify_1073.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 90
PyScratch/sandbox.ps1 PyScratch replay_1073.py '' 150
Copy-Item PyScratch/source-1073.md,PyScratch/1073-replay.json,PyScratch/1073-BTCUSDT.json,PyScratch/1073-ETHUSDT.json NodeScratch
NodeScratch/sandbox.ps1 NodeScratch replay_1073.mjs '' 90
Copy-Item NodeScratch/1073-piner.json PyScratch
PyScratch/sandbox.ps1 PyScratch verify_1073.py '' 90
python -m research.fmz_round24_1073 PyScratch Report.json
```

[Verified trades and cutoff receipts](fmz-round24-1073.json)
