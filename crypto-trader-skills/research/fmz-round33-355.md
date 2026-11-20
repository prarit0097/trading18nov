# FMZ #355 Enhanced Fish Net historical replay

The saved strategy uses Binance USD-M BTCUSDT from September 4 to
September 11, 2023 UTC exclusive. The chart period is 30 minutes,
with a 15-minute base. ETHUSDT is tested over the same window.
The published FMZ argument table resolves two conflicting threshold
defaults in the script to −2.41 and +2.43. Pine v3 is retained.
The source input and horizontal line style use their corresponding
legacy spellings. The archived `n` bar counter, its documented alias
and an inactive Hilbert-branch control all agree on the full default
replay. Removing the two unpriced exit calls also leaves all orders,
plots and equity records identical in the offline runtime.
[Pinned source and exported defaults](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/Enhanced-Fish-Net-Strategy.md#strategy-arguments) · [FMZ source page](https://www.fmz.com/strategy/426455) · [Pine legacy symbol migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-4/)

The archived profile initializes on the first candle in the saved
window. The length stays at its 108-bar minimum. An independent
calculation reproduces the center-of-gravity transform, oscillator
and every entry flag. The original integer midpoint is 54. A 54.5
comparison changes 110 oscillator values per market.

The six long entries fill at the next open with five ticks of
slippage. Each has a fixed 300-tick stop and a trailing stop with a
150-tick activation and 50-tick offset. Exit fills also include the
source's five ticks of slippage. An independent path model matches
all native chart fills. Five ambiguous one-minute periods were then
resolved with Binance trade IDs, millisecond times and trade prices.
All five have complete and matching OHLC and volume. One BTC trailing
stop fired at 25,764.00 with slippage, compared with 25,774.10 on the
chart path. The lower realized equity shrank the later BTC order from
3.875 to 3.873 base units. The other five modeled exit prices agreed.
[Binance official USD-M raw trade and candle formats](https://github.com/binance/binance-public-data#futures)

| Market | Closed | Gross win rate | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 2 | 100% | 0% | 171.32 | −128.85 | 128.85 |
| ETHUSDT | 4 | 25% | 0% | −495.85 | −1,094.92 | 1,094.92 |
| Pooled | 6 | 50% | 0% | −324.53 | −1,223.76 | 1,223.76 |

The 100,000 USDT starting capital per symbol and 100%-of-equity sizing
use the source declaration. Gross P&L includes declared slippage. The
after-fee comparison deducts a 0.075% fee per side on the exact same
lots, with no fee feedback into sizing. Drawdown follows realized
equity. All positions close within the tested window. The test uses an
offline historical fill model. Raw prints resolve the price path,
while spread, liquidity and queue position are outside the benchmark.

## Reproduce

Use the pinned source as `PyScratch/source-355.md`. The report records
the Binance archive paths and checksums for the 15-minute and one-minute
files and all three raw-trade days. Use the Round 11 Pine Compat runtime
and isolated Python launcher.
[Round 11 pinned runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round33_355_stage Public15Min PyScratch
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round33_355_runner.py PyScratch/probe_355.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 45
PyScratch/sandbox.ps1 PyScratch probe_355.py '' 120
python -m research.fmz_round33_355 PyScratch Public1Min PublicDailyTrades Report.json
```

[Verified closes, costs and raw price-path receipts](fmz-round33-355.json)
