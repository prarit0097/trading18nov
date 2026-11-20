# FMZ #1216 dual-session DEMA and bracket replay

The pinned strategy uses three double exponential moving averages with
lengths 25, 50 and 100. It enters when the fast curve crosses both slower
curves on the same 15-minute candle. The default weekday windows are
03:00–11:00 and 08:00–16:00 UTC. The entry uses one base-asset unit and
its bracket uses a 50-tick target and a 100-tick stop. The BTCUSDT archive
sets a 5-minute host base period. ETHUSDT uses the same archived inputs
on a second contract.
[Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E4%B8%89%E9%87%8DEMA%E9%A1%BA%E5%8A%BF%E7%AD%96%E7%95%A5Triple-EMA-Momentum-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/428000)

The archived starting-capital property assignment fails to compile. The
replay declares its 50,000-USDT literal in the strategy header and retains
the original order body. The normalized Pine v4 and v5 chart-only runs
match exactly. The v5 migration makes the v4 weekday default explicit
and enables the complete 5-minute source for the base-period variant.
The independent calculations verify all three curves and both session
signal pairs. A coverage control drops a 5-minute group and reaches the
runtime's documented fallback warning.
[TradingView weekday migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/) · [TradingView Bar Magnifier](https://www.tradingview.com/pine-script-docs/concepts/strategies/#bar-magnifier)

The saved 2023-09-19 through 2023-09-26 UTC range produces zero fills
on both markets. The two comparison ranges produce 19 settled positions
across BTC and ETH. Their market entry prices match both models. Actual
5-minute data changes five chart-only target exits into stops and one stop
into a target. A synthetic bracket holds the parent OHLC constant and
reproduces both lower-candle orders. The report retains the native
15-minute timestamp and the first effective 5-minute candle for each
modeled exit. The primary results use the native OHLC path within that
5-minute candle.

| UTC period | BTC closes | ETH closes | Pooled gross USDT | Pooled after-fee USDT |
|---|---:|---:|---:|---:|
| Saved September 2023 | 0 | 0 | 0.00 | 0.00 |
| August 2026 | 5 | 5 | -22.00 | -561.63 |
| September–October 2026 | 4 | 5 | -27.00 | -544.56 |

The fee comparison deducts 0.075% per side from the verified fills.
The original zero-commission run supplies gross P&L. Drawdown follows
closed-trade equity. The saved-period workbook rows have blank win
rates because there are zero closed trades.

## Reproduce

Use the two official September 2023 Binance 5-minute ZIPs and their
checksum files. The selected saved range contains only traded candles.
Prepare the four Round 13 comparison minute envelopes and reuse the
Round 11 isolated runtime. Save the archive as
`Scratch/source-1216.md`.
[Round 13 minute inputs](fmz-round13-2864.md) · [Round 11 Pine runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round18_1216_stage Saved5mZips Scratch research/fmz-round13-2864.json Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round18_1216_runner.py Scratch/verify_1216.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch probe_1216.py '' 180
Scratch/sandbox.ps1 Scratch verify_1216.py '' 180
python -m research.fmz_round18_1216 Scratch Report.json
```

[Verified results and six changed bracket executions](fmz-round18-1216.json)
