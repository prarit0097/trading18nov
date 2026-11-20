# FMZ #3805 Pine v2 integer-coefficient replay

The archive compares two Kaufman adaptive moving averages and two
fractal adaptive averages. An order requires both pairs to have the
same strict direction. It saves Binance USD-M BTCUSDT from 2023-01-25
to 2024-01-31 UTC exclusive, with a daily chart and hourly base.
ETHUSDT is the independent comparison.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%A4%9A%E5%91%A8%E6%9C%9F%E8%87%AA%E9%80%82%E5%BA%94%E8%B5%B0%E5%8A%BF%E9%A2%84%E6%B5%8B%E7%AD%96%E7%95%A5Multi-cycle-Adaptive-Trend-Forecast-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/440714)

The declared Pine v2 code uses later request syntax on two plots. At
the saved current-timeframe default both requests have the same symbol
and period as the chart. The replay evaluates those two series in
their local context and preserves all trading statements.

With legacy integer division, the four Kaufman coefficients are zero.
Both recurrences start at zero, so their values stay equal and every
strict entry comparison is false. The independent arithmetic agrees
with the runtime and the unchanging cash balance at all 742 daily
observations. The two markets have zero orders, zero realized P&L and
zero drawdown. Win rate has no denominator.
[Pine v3 historical arithmetic](https://www.tradingview.com/pine-script-docs/v3/language/operators/#arithmetic-operators) · [Binance market data](https://github.com/binance/binance-public-data#futures)

An arithmetic control replaces the twelve integer numerator literals
in the smoothing expressions with decimal literals. It produces five
BTC and three ETH order events. The report keeps this control outside
performance. The archived FMZ host's numeric promotion is unconfirmed.
The recorded replay uses the documented legacy Pine arithmetic and the
pinned offline v2 compatibility runtime.
[FMZ arithmetic guidance](https://www.fmz.com/digest-topic/9637) · [Modern Pine fractional division](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/#fractional-division-of-constants)

## Reproduce

Download the public Binance hourly archives and checksum files listed in
the report. Save the pinned source at `Scratch/source-3805.md` and reuse
the Round 11 Pine Compat isolated runtime.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round27_3805_stage PublicHours Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round27_3805_probe.py Scratch/replay_3805.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_3805.py '' 90
python -m research.fmz_round27_3805 Scratch Report.json
```

[Verified replay and numeric controls](fmz-round27-3805.json)
