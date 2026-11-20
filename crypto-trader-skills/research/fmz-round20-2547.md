# FMZ #2547 moving-average replay

The source enters one base-asset unit when the price, four smoothed moving
averages (3, 6, 9 and 50 bars) and the 200-bar EMA are strictly aligned.
Its bracket has a 300-tick target and 300-tick stop. Entries can occur at
any hour. The close-all rule checks weekday 03:00–10:45 UTC membership
at each hourly open. The saved FMZ wrapper selects Binance USD-M BTCUSDT
and 1-hour chart with 15-minute base candles, from 2023-10-24 to 2023-11-23
UTC exclusive. Its Pine title refers to EURUSD. The results use the saved
crypto wrapper and a separately funded ETHUSDT comparison.
[Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%9D%9A%E5%AE%9E%E7%A8%B3%E5%81%A5%E7%9A%84%E7%A7%BB%E5%8A%A8%E5%B9%B3%E5%9D%87%E7%B3%BB%E7%BB%9F%E7%AD%96%E7%95%A5Solid-Moving-Average-System-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/433113)

The legacy wallet assignment fails compilation. The compatibility replay
moves the identical 50,000 capital literal to the header. The legacy v4
and weekday-preserving v5 chart outputs agree on all numeric plots and the
broker ledger. The independent audit verifies both instruments' averages,
session flags, entries, bracket paths and hourly cash. Across 1,440 chart
candles and 5,760 base candles it reconciles 536 order fills and 268 closed
lots. Both books end flat. One BTC signal on the final bar is outside the
recorded execution window. An isolated fixture verifies that the session
market exit fills at the following hourly open. All archived fills close
through a bracket before that exit applies. Removing one complete base
group produces the fallback warning. The full replay has zero warnings.
[Pine session migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#changed-the-default-session-days-for-time-and-time_close) · [Bar Magnifier order model](https://www.tradingview.com/pine-script-docs/concepts/strategies/#bar-magnifier)

From 15:15 through 16:29 UTC on 2023-11-10, five official BTC quarter-hour
candles have zero trades and repeat the prior price. The primary model
keeps their values in the original chart but skips them during broker
traversal. Exactly one BTC lot changes. Its 16:00 signal-window fill is
modeled at the first positive-volume child open at 16:30, 37,447.60 USDT,
then at the 37,417.60 stop. The unfiltered model enters at the stale
37,118.40 carried price and scores +329.20 USDT on that lot. The filtered
model records −30.00 USDT. The exchange candles support a traded-price
simulation. Executable quotes, depth and individual fills remain unknown.
[Binance public market-data schema](https://github.com/binance/binance-public-data#futures)

The native zero-commission replay supplies gross P&L. A separate 0.075%
fee per side is applied to the same quantities and prices. Fees exclude
funding, spread and slippage. Drawdown tracks closed-trade equity. Each
market starts with 50,000 USDT in the simulator.

| Market | Closes | Gross win rate | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 138 | 48.55% | 0.00% | −120.00 | −7,640.24 | 7,640.24 |
| ETHUSDT | 130 | 51.54% | 33.08% | 12.00 | −368.58 | 369.26 |
| Pooled | 268 | 50.00% | 16.04% | −108.00 | −8,008.81 | 8,008.81 |

## Reproduce

Fetch the four Binance 15-minute ZIPs and their checksum files listed in
the report. Save the pinned archive as `Scratch/source-2547.md`. Use the
Round 11 Pine Compat package and isolated Python launcher.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round20_2547_stage PublicInputs Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round20_2547_probe.py Scratch/replay_2547.py
Copy-Item research/fmz_round20_2547_runner.py Scratch/verify_2547.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_2547.py '' 120
Scratch/sandbox.ps1 Scratch verify_2547.py '' 120
python -m research.fmz_round20_2547 Scratch Report.json
```

[Verified results, ledger and public-data receipts](fmz-round20-2547.json)
