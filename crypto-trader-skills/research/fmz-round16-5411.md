# FMZ #5411 archived clock replay

The pinned strategy trades Binance USD-M BTCUSDT on daily candles. It
calculates EMAs with default lengths 30 and 300 despite the short EMA's
display name. During its last-30-day window, a close above the long
EMA submits a limit buy at the short EMA. Quantity is 10% of equity
divided by that EMA. The defined bracket uses a 10% profit target and
a 5% stop relative to the short EMA. The ETHUSDT run applies the same
defaults to a second contract.
[Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E8%B6%8B%E5%8A%BF%E8%B7%9F%E8%B8%AA%E5%9E%8BEMA%E5%8F%8C%E7%BA%BF%E9%99%90%E4%BB%B7%E4%B9%B0%E5%85%A5%E7%AD%96%E7%95%A5-Dual-EMA-Trend-Following-Strategy-with-Limit-Buy-Entry.md) · [FMZ strategy page](https://www.fmz.com/strategy/474633)

The FMZ header's saved wall times are interpreted as UTC. The exact
archived source receives a fixed native replay clock of 2024-12-09
08:00 UTC. Its original calendar expression resolves to 2024-11-09
00:00 UTC on every bar. Calendar fixtures cover month underflow and a
cross-year result. Omitting the explicit clock produces the engine's
expected error. Market inputs contain 1,812 fully closed candles per
contract, from 2019-12-24 through 2024-12-08. Every one of the 30 eligible
days per market matches Binance's archived monthly checksums and prices.
[TradingView clock and timestamps](https://www.tradingview.com/pine-script-docs/concepts/time/) · [FMZ host settings](https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving) · [Binance futures kline API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)

Each market submitted 30 limits. All 29 observed subsequent daily lows
stayed above their working limits, with minimum clearance of 132.20 USDT
for BTC and 138.89 USDT for ETH. Each final submission arrived on the last
bar and had no subsequent candle in this replay. The result for each
contract is zero fills and zero opened or closed positions. Both EMA
curves, the entry rule and requested quantity match an independent
calculation. The two workbook rows record zero settled P&L and leave
win rate blank.

Three synthetic controls run the same source through a touched buy limit,
a favorable opening gap and two bracket sequences on candles touching
both exits. The native touch uses the Pine limit value, and native bracket
prices use the verified direction-specific tick application. These
controls confirm fill behavior independently of the historical outcomes.

## Reproduce

Fetch the four daily REST responses and the four monthly ZIPs with their
checksum files from the report manifest. Keep them in local data folders.
Place the pinned Markdown in `Scratch/source-5411.md`. Reuse the Round 11
Pine Compat package, isolated Python launcher and denial probe.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round16_5411_stage DailyREST MonthlyZips Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round16_5411_runner.py Scratch/probe_5411.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch probe_5411.py '' 120
python -m research.fmz_round16_5411 Scratch Report.json
```

[Verified coverage and data manifest](fmz-round16-5411.json)
