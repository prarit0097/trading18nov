# FMZ #1214 effective EMA reversal replay

The archive uses one-minute Binance BTCUSDT futures candles. Its two entry
branches use five-, 20- and 50-bar EMAs, a crossover or crossunder, and the
original change-from-previous-close filter. Its explicit order size is one
base-asset unit. Each separate replay starts with 50,000 USDT and the
archived per-side commission is 0.004%. ETHUSDT tests the same archived
rules on a second contract. [Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E4%B8%89%E9%87%8DEMA%E8%BF%BD%E8%B8%AA%E6%AD%A2%E6%8D%9F%E7%AD%96%E7%95%A5Triple-EMA-With-Trailing-Stop-Loss-Strategy.md) · [FMZ description](https://www.fmz.com/strategy/429478)

The strategy assigns a `StopLoss` variable. All four `strategy.exit` calls
supply identifiers alone and leave that value unused. TradingView's legacy
migration documentation describes these calls as having no effect and
permits removing them. The normalized v4 source and mechanically converted
v5 source trigger only the four corresponding arity errors in the negative
controls. Omitting the four parameter-free calls preserves the effective
archived position reversals on opposite entry signals.
[TradingView v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#strategyexit-now-must-do-something)

Both Pine versions run against the same complete checksummed one-minute
Binance data. Their original plots and full broker outputs must match. An
independent Python calculation uses the runtime's verified SMA-seeded EMA
recurrence and checks every plot value, both entry conditions, next-open
outcomes, quantity, fees and ending equity. The first eligible signal can
occur at the first bar with a complete 50-period EMA. Configuration and
eligibility are verified on the source's actual default parameters. This
study identifies the historical effects of the archived code under the
pinned Pine Compat emulator.
[Binance public market archives](https://data.binance.vision/) · [Pine Compat source](https://github.com/helenananaa/pine-compat-runtime/tree/c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc)

Across 264,960 chart bars, the four runs verified 1,750 settled trades.
An opposite signal closes the previous unit and opens the reversed unit.
The backtest uses the default legacy margin settings and marks ending
exposure. Modeled execution costs consist of the archived commission.

| UTC sample | Contract | Closed | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---|---:|---:|---:|---:|
| August 2026 | BTCUSDT | 267 | 4,960.20 | 3,460.64 | 9,332.00 |
| August 2026 | ETHUSDT | 307 | 105.11 | 53.27 | 384.97 |
| September–October 2026 | BTCUSDT | 583 | -30,699.90 | -34,491.57 | 42,025.20 |
| September–October 2026 | ETHUSDT | 593 | -240.30 | -359.61 | 703.60 |

## Reproduce

Reuse the four Round 13 FMZ #2864 chart files, the shared chart input manifest,
the pinned Round 11 `priced-runtime` package, Python AppContainer and denial
probe. Place the exact archived bytes in `Scratch/source-1214.md`. The prior
market data preparation verifies the official monthly archive checksums.
[Round 13 feed reproduction](fmz-round13-2864.md) · [Round 11 runtime build](fmz-round11-magnifier-priced.md)

```powershell
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round14_1214_runner.py Scratch/replay_1214.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_1214.py probe 120
Scratch/sandbox.ps1 Scratch replay_1214.py '' 840
python -m research.fmz_round14_1214 Scratch Report.json
```

[Trade and workbook metrics](fmz-round14-1214.json)
