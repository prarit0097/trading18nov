# FMZ #1070 Vitalik Scalper historical comparison

The archive supplies a Pine v4 strategy and its input defaults, with no
saved market, candle period, date window or FMZ execution settings. This
comparison uses Binance USD-M BTCUSDT and ETHUSDT from January 1 through
February 1, 2024 UTC exclusive. The 30-minute decision charts aggregate
2,976 official 15-minute candles per market. The default Heikin-Ashi
requests use the same time frames and a series seeded at the start of the
comparison. Real-market OHLC supplies the fill model.
[Pinned strategy source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/Vitalik-Scalpe.md) · [FMZ strategy page](https://www.fmz.com/strategy/376261) · [Binance public market archives](https://data.binance.vision/)

The archived entry runs on the next open after the basic long or short
condition. The separate reversal tracker can still be uninitialized
when the entry is submitted. It then supplies zero ticks for both exits
and leaves the absolute target undefined. BTC had four such same-open
closes and ETH had twelve. Both runtimes reproduce this behavior when the
entry and exit were submitted together at the prior close. A separate
control submits the bracket after entry and exits one bar later.
In the original Pine v4/v5 priority control, the absolute target of 105
wins over a two-tick target of 102. Pine Compat fills 105. Both Piner
0.13.0 backends fill 102, so their output is used only to characterize the
engine difference.
[Legacy TradingView broker rules](https://www.tradingview.com/pine-script-docs/v4/essential/strategies/#broker-emulator) · [TradingView exit precedence](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/#strategy-exit-evaluates-parameter-pairs)

The literal replay executes 31 BTC and 45 ETH exits at prices between
Binance ticks. The grid-safe comparison rounds absolute sell targets up
and buy targets down to preserve the source's price protection. The
original signal, entry, stop, reversal and ATR close logic is retained.
The target adjustment changes those 76 execution prices. Compounding
also changes thirteen ETH position sizes. Entry and exit bar assignments
are the same in both versions. The independent audit matched every
execution price against the first eligible event in 44,640 one-minute
candles per market. One BTC 30-minute bar reached both prices. Its first
eligible minute reached only the stop. The modeled fills use candle
prices and trigger levels, with no bid/ask or queue data.
[Binance USD-M price filters](https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition#price_filter)

| Market | Closed | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 80 | 57.50% | −1,888.31 | −2,305.10 | 2,649.58 |
| ETHUSDT | 99 | 55.56% | −750.99 | −1,292.34 | 1,668.95 |
| Pooled | 179 | 56.42% | −2,639.29 | −3,597.44 | 4,199.46 |

The table uses the grid-safe comparison. It starts each asset with
10,000 USDT and sizes market entries at 100% of next-open equity with a
0.001 quantity step and the declared 0.03% commission per side. Gross P&L
removes commissions from the same closed lots. Drawdown uses realized
equity. One short remains open per market. Spread, funding and
effectiveness outside the selected period are outside this comparison.

FMZ's documented position average includes handling fees, whereas
the portable model uses the fill average. That difference reaches both
legacy absolute take-profit formulas. The FMZ interface sets strategy
options including starting balance and costs that this archive supplies
only in the Pine declaration. The results apply to the portable
historical benchmark. FMZ host parity and trading qualification remain
unverified.
[FMZ position average](https://www.fmz.com/doc/9293#strategy.position_avg_price) · [FMZ strategy settings](https://www.fmz.com/doc/9293#strategy)

## Reproduce

Fetch the 15-minute and 1-minute Binance archives and checksum sidecars
listed in the report. Save the pinned FMZ archive as
`PyScratch/source-1070.md`. Reuse the Round 11 pinned Pine Compat runtime
and both isolated runtime launchers. NodeScratch also needs the pinned
Piner 0.13.0 distribution, npm tarball and matching isolation probe
receipt.
[Round 11 Pine Compat runtime](fmz-round11-magnifier-priced.md) · [Round 7 Piner runtime](fmz-round7-magnifier.md)

```powershell
python -m research.fmz_round30_1070_stage PublicInputs PyScratch
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round22_2994_probe.py PyScratch/replay_2994.py
Copy-Item research/fmz_round30_1070_runner.py PyScratch/replay_1070.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 45
PyScratch/sandbox.ps1 PyScratch replay_1070.py '' 120
Copy-Item PyScratch/1070-fixture-inputs.json NodeScratch
Copy-Item research/fmz_round30_1070_fixtures.mjs NodeScratch/run_1070_fixtures.mjs
NodeScratch/sandbox.ps1 NodeScratch run_1070_fixtures.mjs '' 60
python -m research.fmz_round30_1070 PyScratch PublicInputs NodeScratch/1070-piner-fixtures.json Report.json
```

[Verified performance and diagnostic receipts](fmz-round30-1070.json)
