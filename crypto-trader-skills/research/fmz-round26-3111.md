# FMZ #3111 saved BTC KAMA/HMA replay

The source enters long when its Hull-style weighted average rises. It
enters short when that average falls and the close is below the Kaufman
adaptive moving average. The opposing flag closes the current position.
The saved Binance BTCUSDT period is 2024-01-29 through 2024-02-05 UTC
exclusive, with a 45-minute chart and 5-minute base.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%9F%BA%E4%BA%8E%E5%8D%A1%E9%A9%AC%E5%92%8C%E5%9D%87%E7%BA%BF%E7%9A%84%E8%B6%8B%E5%8A%BF%E8%B7%9F%E8%B8%AA%E7%AD%96%E7%95%A5Kama-and-Moving-Average-Based-Trend-Following-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/441140)

The archived v2 script mixes in later names for a request using the
current symbol and timeframe. The v2 compatibility route runs the
unchanged recursive KAMA directly in that context. A v5 typed request
and a direct v5 KAMA produce the same indicators and orders as the v2
route. The half-length calculation preserves v2 integer division of
seven by two. The float division sensitivity changes the series and
order results.

On the original BTC market the archived fill-recalculation mode and the
confirmed-bar-only control match. The 5-minute replay also matches. All
59 order events, 29 closed lots and 224 equity marks are independently
reconciled. Each modeled entry or close uses the first reported 5-minute
open of the next 45-minute period.
[Binance market-data archives](https://github.com/binance/binance-public-data#futures)

| Market | Closed | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 29 | 20.69% | −505.50 | −2,364.70 | 3,987.05 |

The table uses closed-trade equity. Gross uses the archived zero
commission. The cost comparison deducts 0.075% per side from the same
fills. One short remains open. The final marked equity before the fee
comparison is 999,524.20 USDT on the default 1,000,000 USDT book.

The ETH comparison needs a causal fill model. At chart bars 76 and 110
the historical fill-recalculation emulator enters and reverses at the
same open. Each reversal needs the sell decision from the completed
45-minute candle. The independent open-only reconstruction gives a buy
at both times. The same issue remains when 5-minute data is supplied.
The report retains both controls and excludes ETH from performance.
[TradingView historical fill recalculation](https://www.tradingview.com/pine-script-docs/concepts/strategies/#calc_on_order_fills)

## Reproduce

Download the public Binance 5-minute monthly ZIPs and their checksum
files from the report. Save the pinned source as `Scratch/source-3111.md`.
Reuse the Round 11 Pine Compat isolated runtime.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round26_3111_stage Public5m Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round26_3111_probe.py Scratch/replay_3111.py
Copy-Item research/fmz_round26_3111_runner.py Scratch/verify_3111.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_3111.py '' 120
Scratch/sandbox.ps1 Scratch verify_3111.py '' 90
python -m research.fmz_round26_3111 Scratch Report.json
```

[Verified BTC result and ETH diagnostic receipts](fmz-round26-3111.json)
