# FMZ #4671 session breakout replay

The pinned Pine v4 source trades a fast two-hour SMA breakout during the
03:00 UTC hour. The prior close relative to the current 200-hour EMA
sets the permitted direction. Orders use one unit of the base asset.
The 66-tick stop is relative to the entry fill, giving a 6.60 USDT
distance on BTCUSDT and 0.66 USDT on ETHUSDT. The archive calculates
a risk-based size as a separate value. The entry calls use the broker's
default quantity. The historical tests follow the executable order body.
[Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E6%94%B6%E7%9B%98%E7%AA%81%E7%A0%B4%E6%97%A5%E5%86%85%E4%BA%A4%E6%98%93%E7%AD%96%E7%95%A5Breakout-Day-Trading-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/428812)

The archived declaration was commented out. The active code also tries
to write to the broker's starting-capital property. The standalone
replay uses a strategy declaration with the active 50,000-USDT literal
and retains the original order body. A separate run uses the commented
10,000-USDT declaration and its 0.00008-USDT per-contract commission.
The two versions produce identical orders, positions and fill prices.
The latter's net amount differs by the two explicit per-contract fees.

The replay uses Pine v4's weekday session default. The session-close
condition becomes true outside the archived 03:00–09:45 time range.
The 10:00 hourly bar first qualifies for that market exit, which then
fills at the next open if a stop has yet to close the position. The source's
time predicate evaluates to `na` outside the range, and the v4 negation
is true in the verified runtime. The session fixture checks both
weekday and weekend candle boundaries. The independent calculation
also checks every moving average value and both entry conditions.
[TradingView session defaults](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#changed-the-default-session-days-for-time-and-time_close) · [TradingView orders](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/)

Tests use the saved 2023-09-08 to 2023-10-08 UTC dates and the project's
two later comparison windows. The two markets cover 5,856 hourly bars
with 23,424 checksummed 15-minute bars. All 56 fills reconcile to
the relevant base-candle opening prices or first stop contacts. There
are 28 settled positions, with 27 stopped and one closed by the session
rule. The main declaration's zero commission defines gross P&L. The
workbook's fee sensitivity deducts 0.075% per side on the same fills.
Drawdown uses realized equity in USDT.
[Binance public archives](https://data.binance.vision/) · [FMZ host backtest settings](https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving)

## Reproduce

Use the four official 2023 Binance 15-minute ZIPs and their checksums
from the report. Reuse the Round 12 hourly and 15-minute comparison inputs,
the Round 11 runtime and the isolated Python launcher. Save the exact
archive in `Scratch/wallet-4671.md`.
[Round 12 comparison data](fmz-round12-5708.md) · [Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round17_4671_stage Archived15mZips Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round15_3604_runner.py Scratch/probe_3604.py
Copy-Item research/fmz_round15_3604_base.py Scratch/control_3604_base.py
Copy-Item research/fmz_round17_4671_runner.py Scratch/probe_4671.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch probe_4671.py '' 180
python -m research.fmz_round17_4671 Scratch Report.json
```

[Verified outcomes and metrics](fmz-round17-4671.json)
