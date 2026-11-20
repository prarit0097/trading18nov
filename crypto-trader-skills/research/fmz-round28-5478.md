# FMZ #5478 PSAR and EMA USD replay

The saved Pine v4 source uses PSAR reversals confirmed by the relation
between the 9-period and 21-period EMAs. Its default mode enters long
and closes that position on confirmed bearish reversals. Shorts, the
optional PSAR stop and the EMA200 filter are disabled. The source
reassigns its calculated date condition to `true`. Two replay clocks
366 days apart therefore produce the same positions, fees and marks.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E8%B7%A8%E5%9D%87%E7%BA%BF%E5%A4%9A%E6%8C%87%E6%A0%87%E4%BA%A4%E6%98%93%E7%AD%96%E7%95%A5Parabolic-Stop-and-Reserve-Multi-Indicator-Trading-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/436902)

The saved Binance BTCUSDT interval is 2023-12-20 to 2023-12-27 UTC
exclusive with a 45-minute chart and 5-minute base. ETHUSDT uses the
same rules and its own book. Complete one-minute Binance archives
build both intervals. The independent replay matches 448 sets of
signals and marked balances, all ten next-open fills and all five
settled positions. Execution prices agree with the corresponding
first 5-minute opening price. Both books finish flat.
[Binance public futures data](https://github.com/binance/binance-public-data#futures)

Each book starts with USD 5,000. Placement budgets 20% of equity with
the 0.1% entry fee included, uses the next opening price and rounds
down to the 0.001 quantity step. The previous completed Coinbase
USDT-USD close translates the venue amount. Gross excludes commission.
Net uses the source's 0.1% per-side fees. Drawdown tracks closed-trade
equity.
[Coinbase public candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles) · [Archived fee-aware sizing model](fmz-round10-magnifier-market.md)

| Market | Closed | After-fee win rate | Gross USD | After-fee USD | After-fee drawdown USD |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 3 | 0% | −28.49 | −34.27 | 34.27 |
| ETHUSDT | 2 | 50% | −2.84 | −6.85 | 38.90 |
| Pooled | 5 | 20% | −31.34 | −41.12 | 58.14 |

## Reproduce

Download the official December Binance one-minute archives and their
checksum files from the report. Save the Coinbase API response as
`USDTUSD.json`, and the pinned source as `Scratch/source-5478.md`.
Reuse the isolated Round 11 Pine Compat environment.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round28_5478_stage Public1m USDTUSD.json Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round22_2994_probe.py Scratch/replay_2994.py
Copy-Item research/fmz_round22_2994_runner.py Scratch/verify_2994.py
Copy-Item research/fmz_round28_5478_probe.py Scratch/replay_5478.py
Copy-Item research/fmz_round28_5478_runner.py Scratch/verify_5478.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_5478.py '' 90
Scratch/sandbox.ps1 Scratch verify_5478.py '' 90
python -m research.fmz_round28_5478 Scratch Report.json
```

[Verified USD settlements and data receipts](fmz-round28-5478.json)
