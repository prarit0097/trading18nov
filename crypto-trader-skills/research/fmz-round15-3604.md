# FMZ #3604 archived order-block replay

The pinned source uses hourly Binance perpetual candles and enters when
five consecutive candles confirm a prior opposite-color bar. The default
order is one base-asset unit. Its market closes compare open profit with
the starting capital plus settled net P&L. The thresholds in
the executable code are +2% and -1% of that denominator. ETHUSDT replays
the same default rules on a second contract.
[Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%9F%BA%E4%BA%8E%E8%AE%A2%E5%8D%95%E5%9D%97%E7%9A%84%E5%8A%A8%E9%87%8F%E7%AA%81%E7%A0%B4%E7%AD%96%E7%95%A5The-Order-Block-Momentum-Breakout-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/442822)

The source attempts a dotted assignment of 50,000 to
`strategy.initial_capital`. That single assignment prevents compilation.
The replay relocates the archived literal to the strategy declaration and
keeps all four original denominator reads. Pinning the denomination to the
same literal directly in those four expressions yields identical full
runtime output. A separate comparison leaves the broker default capital of
1,000,000 intact and confirms that the resulting account equity differs.
The strategy title and order formulas otherwise come from the archive.
[TradingView strategy properties](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/)

The independent calculation verifies candle direction, threshold timing,
market fills at the next hourly open, exposure and broker cash. Synthetic
controls show a queued explicit close executes before a same-open opposite
entry, and a same-side repeat preserves only the queued close. The four
real windows contain 135 matched fills and 84 closes, comprising 34 stop
thresholds, 15 profit thresholds and 35 reversals. The source declares zero
commission. The fee sensitivity deducts 0.075% per side from the same
settled fills. The drawdown calculation uses realized equity.

The archive's FMZ host header names a 15-minute base period. The v4 source
uses hourly market order decisions. A separate price control rebuilds every
hour from 17,664 verified 15-minute bars and reconciles all 135 order prices
against their first 15-minute opens. A compiler fixture confirms the
separate Pine Bar Magnifier feature requires a later language version.
[FMZ host backtest metadata](https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving) · [Binance archives](https://data.binance.vision/)

| UTC sample | Contract | Closed | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---|---:|---:|---:|---:|
| August 2026 | BTCUSDT | 17 | -3,013.20 | -4,731.60 | 4,731.60 |
| August 2026 | ETHUSDT | 9 | 353.51 | 325.17 | 145.63 |
| September–October 2026 | BTCUSDT | 36 | 227.40 | -4,192.56 | 8,223.32 |
| September–October 2026 | ETHUSDT | 22 | -425.28 | -508.31 | 532.51 |

## Reproduce

Reuse the 60-minute and 15-minute evidence feeds from Round 12 #5708,
the pinned Round 11 Pine Compat package, and the Python AppContainer
launcher and isolation probe. Place the pinned archive in
`Scratch/wallet-3604.md`.
[Round 12 market feeds](fmz-round12-5708.md) · [Round 11 runtime build](fmz-round11-magnifier-priced.md)

```powershell
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round15_3604_runner.py Scratch/probe_3604.py
Copy-Item research/fmz_round15_3604_base.py Scratch/control_3604_base.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch probe_3604.py '' 120
Scratch/sandbox.ps1 Scratch control_3604_base.py '' 120
python -m research.fmz_round15_3604 Scratch Report.json
```

[Verified results and order-price checks](fmz-round15-3604.json)
