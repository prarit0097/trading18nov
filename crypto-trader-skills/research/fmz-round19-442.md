# FMZ #442 Ichimoku and directional-movement replay

The pinned Pine v2 strategy submits a one-unit raw order when a 30-minute
candle crosses its seven-bar Donchian midpoint from open to close and the
directional movement index for that side exceeds 20. The default session is
weekdays from 04:00 to 15:00 UTC. The bracket uses a 150-tick stop and
200-tick target. BTCUSDT has a 0.1 USDT tick and ETHUSDT a 0.01 USDT tick.
The saved BTCUSDT dates are replayed from 2023-12-13 to 2023-12-20
UTC exclusive. ETHUSDT tests the same rules on a second contract.
[Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/Ichimoku%E4%BA%91%E9%87%8F%E5%8C%96%E7%9F%AD%E7%BA%BF%E7%AD%96%E7%95%A5Ichimoku-Cloud-Quant-Scalping-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/436096)

The exact archived v2 program runs against the saved 30-minute chart.
A v5 control makes the legacy recurrences and weekday defaults explicit.
Its chart-only run and its run with the complete saved 15-minute base
give the same broker output as v2. The independent calculation checks
the directional indexes, midpoint, both signals and the cash ledger.
Dropping one base group produces the expected fallback warning.
[TradingView legacy recurrence migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-3/) · [TradingView session migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/) · [TradingView Bar Magnifier](https://www.tradingview.com/pine-script-docs/concepts/strategies/#bar-magnifier)

The first bracket becomes active after the order's entry bar. A synthetic
fixture also verifies that a same-direction addition at the next open
preserves the new unit after the earlier reserved lot exits. In the two
historical samples the audit reconciles four such additions and one
opposite raw order. It verifies 80 order fills, 40 closed lots and zero
ending exposure using 672 chart bars and 1,344 historical base candles.

Each run starts with the archived USD 100,000. The prior completed UTC
day's Coinbase USDT-USD close supplies the USD conversion. The original
model's zero commission defines gross P&L. The fee comparison deducts
0.075% per side from the same fills, with each fee translated at its own
UTC effective rate. Drawdown tracks realized equity.
[Coinbase daily candle API](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles) · [Binance public archives](https://data.binance.vision/)

| Market | Closed | After-fee win rate | Gross USD | After-fee USD | After-fee drawdown USD |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 20 | 15% | -872.81 | -2,142.26 | 2,142.26 |
| ETHUSDT | 20 | 20% | -57.40 | -123.77 | 124.68 |
| Pooled | 40 | 17.5% | -930.21 | -2,266.03 | 2,266.03 |

## Reproduce

Fetch the two official December 2023 Binance 15-minute ZIPs and their
checksum files from the report. Save the Coinbase response from the
report's FX endpoint as `PublicInputs/442-usdt-usd-archive-fx.json`.
Put the pinned FMZ archive in `Scratch/source-442.md`. Reuse the
Round 11 Pine Compat package, isolated Python launcher and denial probe.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round19_442_stage PublicInputs Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round19_442_probe.py Scratch/replay_442.py
Copy-Item research/fmz_round19_442_runner.py Scratch/verify_442.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_442.py '' 120
Scratch/sandbox.ps1 Scratch verify_442.py '' 120
python -m research.fmz_round19_442 Scratch Report.json
```

[Verified results and input receipts](fmz-round19-442.json)
