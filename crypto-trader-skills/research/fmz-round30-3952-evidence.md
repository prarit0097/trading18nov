# FMZ #3952 daily confidence timing evidence

The saved BTCUSDT source runs on four-hour bars from 2023-08-14 through
2023-09-13 UTC exclusive. It requires a daily confidence ratio for orders
alongside its Hull, Ichimoku and MACD conditions. The normalized v2
diagnostic removes a stray backtick and uses the Pine v2 ticker alias.
Its decision series and broker output match the explicit lookahead-on
v5 control exactly.
[Pinned FMZ source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%A4%9A%E6%8C%87%E6%A0%87%E7%BB%84%E5%90%88%E7%9A%84%E7%9F%AD%E7%BA%BF%E9%87%8F%E5%8C%96%E4%BA%A4%E6%98%93%E7%AD%96%E7%95%A5Multi-Indicator-Short-Term-Algorithmic-Trading-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/426842)

The independent daily ratio matches every observed confidence value
in both projections. The legacy mode supplies a day's final close
before it occurs. Using available confirmed daily closes changes three
BTC and two ETH entry flags before the corresponding day closes. The
diagnostic closed counts change from four to two on each market. The
saved policy needs an authoritative causal merge rule before any
performance row qualifies.
[TradingView legacy lookahead behavior](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lookahead)

## Reproduce

Use the public Binance monthly one-hour archives and checksums in the
report. Save the pinned source as `Scratch/source-3952.md`. The
diagnostic uses actual 4h and 1D decision prices from those candles.
Use the Round 11 pinned Pine Compat runtime and isolation launcher.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round30_3952_stage PublicHours Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round30_3952_probe.py Scratch/replay_3952.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_3952.py '' 90
python -m research.fmz_round30_3952 Scratch Evidence.json
```

[Verified early-entry timing receipts](fmz-round30-3952-evidence.json)
