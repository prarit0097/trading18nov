# FMZ #1349 Low Scanner restored-header replay

The published Pine v4 source comments out its only strategy
declaration. The unmodified archive fails declared-mode compilation.
The historical comparison activates that exact authored line. It keeps
all signal, sizing and exit expressions as published. This comparison
covers October 24, 2023 UTC, the one-day Binance USD-M BTC window in the
archive, and the same interval on ETH. Each market uses 480 three-minute
decision bars derived from official one-minute candles.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E4%BD%8E%E7%82%B9%E6%89%AB%E6%8F%8F%E6%99%BA%E8%83%BD%E8%BF%BD%E8%B8%AA%E6%B3%95Low-Scanner-Smart-Tracking-Method.md) · [FMZ published header](https://www.fmz.com/strategy/430758) · [Pine declaration rules](https://www.tradingview.com/pine-script-docs/language/script-structure/#declaration-statement)

The two weekly Hull series use 43 complete Binance weeks from January
through October. Their independently calculated last confirmed inputs
match every observed value. The decision line is 26,454.60624 for BTC
and 1,596.13199 for ETH. The 25-bar linear regression starts above the
line and stays above it for the rest of the day. It never produces the
required crossover. The saved day also contains no weekly boundary,
so the separate low-scanner branch remains undefined.

BTC and ETH each have zero orders, zero closes and zero drawdown.
The ledger stays flat at 1,000 USDT per market as declared in the
restored header. Win rates are undefined for this empty trade count.
The authored bracket calls run while the position is flat and emit
undefined-distance diagnostics. An independent control gates those
calls on an open position. The ledger, equity and all observed values
agree with the restored-header benchmark. This test covers the saved
day only and does not exercise the published partial exits.

## Reproduce

Use the pinned FMZ document as `PyScratch/source-1349.md`. The report
lists official Binance daily and one-minute archives and their
checksums. The executable comparison uses the existing Round 11
Pine Compat isolated runtime.
[Round 11 runtime setup](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round34_1349_stage PublicDaily PublicMinutes PyScratch
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round34_1349_runner.py PyScratch/probe_1349.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 45
PyScratch/sandbox.ps1 PyScratch probe_1349.py '' 90
python -m research.fmz_round34_1349 PyScratch Report.json
```

[Verified original declaration check and zero-order results](fmz-round34-1349.json)
