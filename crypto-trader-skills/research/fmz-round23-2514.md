# FMZ #2514 4-hour rating and USD replay

The archived strategy combines a moving-average rating and an oscillator
rating every day. It enters long on a positive score and short on a
negative score. The source describes named EMA, Hull and VWMA votes, but
their active calls use the same SMA helper as the other averages. The
replay preserves those calls, the inactive Ichimoku vote and the saved
4-hour reference timeframe. The BTCUSDT window is 2022-10-17 to
2023-05-14 UTC exclusive. ETHUSDT uses the same dates and rules.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%9D%87%E7%BA%BF%E7%A9%BF%E8%B6%8A%E7%AD%96%E7%95%A5Trend-Following-Strategy-Based-on-Moving-Average-Crossover.md) · [FMZ strategy page](https://www.fmz.com/strategy/430022)

The Pine v4 declaration is normalized by replacing 20 newer request
names with their v4 spelling and qualifying ten bare color values. The
RSI helper receives the archived integer lookback of 14. The four-hour
request is sampled from the last confirmed child in each day. The
isolated three-day control distinguishes that rule from selecting the
first child using lookahead. Every one of the 10,450 moving-average and
oscillator votes and all three rating lines reconcile with an independent
calculation. The two markets use 2,508 four-hour reference candles built
from 10,032 public hourly candles.
[Pine v5 migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/) · [Lower-timeframe request behavior](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lower-timeframes)

The original one-unit exposure reverses in a two-unit market order at
the next daily open. Each price agrees with the first public hourly open.
The replay reconciles 112 closes, 114 total arrival fills and 418 marked
equity values. It uses the previous completed UTC day's Coinbase
USDT-USD close. The exit-day effective FX converts the realized price
change. The comparison charges a 0.075% fee per side, with the opening
and closing fees converted at their own effective rates. Each market
retains one open position at the end.
[Binance public archives](https://data.binance.vision/) · [Coinbase public candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)

| Market | Closed | After-fee win rate | Gross USD | After-fee USD | After-fee drawdown USD |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 55 | 27.27% | 10,252.50 | 8,436.03 | 8,029.82 |
| ETHUSDT | 57 | 24.56% | −632.02 | −766.98 | 1,276.90 |
| Pooled | 112 | 25.89% | 9,620.48 | 7,669.05 | 8,548.90 |

The table uses closed-trade equity. The archived legacy declaration
starts each simulator with USD 500 and leaves margin unconstrained.
Both accounts reach negative marked equity before the fee comparison.
The lowest marks are −437.10 USD for BTC and −131.96 USD for ETH.
The numbers describe the archived simulator and cannot establish that
this position size is feasible for a USD 500 account. Funding, spread
and additional slippage are outside this replay.

## Reproduce

Use the public Binance monthly archives and checksum files in the
report. Save its public Coinbase response as `USDTUSD.json` and the
pinned archive as `Scratch/source-2514.md`. Reuse the Round 11
Pine Compat runtime and isolated launcher.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round23_2514_stage PublicInputs USDTUSD.json Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round23_2514_probe.py Scratch/replay_2514.py
Copy-Item research/fmz_round23_2514_votes.py Scratch/audit_2514.py
Copy-Item research/fmz_round23_2514_runner.py Scratch/verify_2514.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_2514.py '' 150
Scratch/sandbox.ps1 Scratch verify_2514.py '' 90
python -m research.fmz_round23_2514 Scratch Report.json
```

[Verified closure, reversal, FX and data receipts](fmz-round23-2514.json)
