# FMZ #1003 archived opening-range replay

The strategy watches an opening range derived from 30-minute data. The
saved Binance BTCUSDT test runs on one-hour bars with a 15-minute base
from 2023-08-09 to 2023-09-08 UTC exclusive. The saved `v_input_10=true`
setting enables the short rules. ETHUSDT uses the same rules on its
own book. The replay uses Pine v2 names for the symbol and timeframe
and translates display-only plot arrow arguments.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/The-Open-Range-Strategy-with-Dynamic-Profit-Target.md) · [FMZ strategy page](https://www.fmz.com/strategy/426261)

Independent UTC session calculations verify 22 weekday opening sessions
per market. The 09:30–10:00 exclusion window has no hourly bar open
inside it. The 10:00–11:00 trade window appears at 10:00, and the custom
daily clock returns the virtual 09:30 opening value inside the session.
At each 30-minute session start the previous clock value is missing.
The source's unguarded inequality yields no reset. Subsequent values
inside the same session are equal, so its high and low range series
remain missing throughout the replay.
[TradingView session clock and guarded opening example](https://www.tradingview.com/pine-script-docs/v4/essential/sessions-and-time-functions/) · [Binance archived candles](https://github.com/binance/binance-public-data#futures)

Across 1,440 hourly chart candles, 2,880 opening-range reference candles
and 5,760 base candles, both books emit zero signals, orders and fills.
Gross and net P&L are zero, and realized drawdown is zero. There are no
closed trades for a win rate. An explicit missing-value guard produces
10 BTC and 8 ETH order events. That edit remains a diagnostic control.
The strategy results use the archived range gate.

## Reproduce

Use the listed official Binance 15-minute ZIPs and their checksums.
Save the archive as `Scratch/source-1003.md` and reuse the pinned
Round 11 Pine Compat runtime and isolation launcher.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round29_1003_stage Public15m Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round29_1003_probe.py Scratch/replay_1003.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_1003.py '' 120
python -m research.fmz_round29_1003 Scratch Report.json
```

[Verified session and diagnostic receipts](fmz-round29-1003.json)
