# FMZ #1985 higher-timeframe timing evidence

The saved BTCUSDT strategy uses a 5-minute chart with a 1-minute broker
base. Entry depends on a 120-minute trend and a MACD gate. The source
declares Pine v2 and writes the three higher-timeframe calls with a
later `request.security` namespace. The pinned runtime cannot infer the
types of four implicit recursive declarations in the literal file.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%8F%8C%E5%9D%87%E7%BA%BFSuperTrend%E9%87%8F%E5%8C%96%E4%BA%A4%E6%98%93%E7%AD%96%E7%95%A5Dual-Moving-Average-Supertrend-Quantitative-Trading-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/441065)

The diagnostic ports the definitions to v5 and compares the legacy
lookahead-on projection with the confirmed-only projection. Every
higher-timeframe value matches the independently aggregated market
data in its expected position. The legacy mode sees each final 120-minute
close on the first 5-minute bar inside that period. The confirmed mode
first sees it when the 120-minute candle closes.
[TradingView legacy security timing](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lookahead)

The two modes differ on 20 BTC and 12 ETH entry flags. Each difference
precedes its corresponding 120-minute close. Switching projections also
changes the diagnostic trade counts from 68 to 58 on BTC and from 50 to
47 on ETH. These counts show the effect of the two-hour projection on
signals. Neither variant supplies historical performance.
The original strategy remains pending until the archived FMZ merge
setting or an authorized causal rule is established.

## Reproduce

Use the public January and February 2024 Binance 5-minute archives and
checksums in the report. Save the pinned source as `Scratch/source-1985.md`.
Reuse the Round 11 Pine Compat isolation directory. The diagnostic
stops at decision timing and requires only the traded 5-minute data.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round28_1985_stage Public5m Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round28_1985_probe.py Scratch/replay_1985.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_1985.py '' 90
python -m research.fmz_round28_1985 Scratch Evidence.json
```

[Verified decision-timing evidence](fmz-round28-1985-evidence.json)
