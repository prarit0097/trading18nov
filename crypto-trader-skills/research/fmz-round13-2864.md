# FMZ #2864 VWAP and RSI replay

The archived Pine strategy trades short on an RSI cross below 85. It closes
the short after the delayed cross below 30 or a current cross above 30. RSI
uses the 20-period Wilder average of changes in the session VWAP of close.
The archive uses the chart timeframe and disables the optional Laguerre
filter by default. Its host configuration selects Binance BTCUSDT perpetuals
and one-minute candles. ETHUSDT is an independently funded cross-asset
replay of the same defaults.
[Pinned archived source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%9F%BA%E4%BA%8ERSI%E6%8C%87%E6%A0%87%E7%9A%84%E8%B7%A8%E6%97%B6%E9%97%B4%E6%A1%86%E6%9E%B6%E7%AD%96%E7%95%A5VWAP-RSI-Oversold-Crossunder-BTC-Short-Strategy.md) · [FMZ description](https://www.fmz.com/strategy/437003)

The Pine v4 to v5 migration updates namespaces, typed inputs, the short
entry constant and display transparency. It retains the original same-context
`request.security` call and the exit expression's operator precedence. The
independent calculation resets VWAP at each UTC midnight and maintains RSI
history across sessions. For every one of the 264,960 actual chart bars, it
matches the runtime's chart VWAP, chart and requested RSI, and crosses. The
extra observer plots leave the native order, trade, position and equity output
identical.
[TradingView v5 migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/) · [TradingView's chart-timeframe request semantics](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#timeframes)

The four offline replays start with 1,000 USDT each and size shorts at 50%
of equity. The ledger audit independently checks the next minute's opening
price, 0.001 base-asset lot step, and cash settlement. It reconciles 733 fills,
366 closed trades and one open position. The archive specifies no fees or
slippage. The cost sensitivity subtracts 0.075% per side from each verified
closed lot with quantity held fixed. Drawdown uses realized equity. Funding
is outside the replay model.

| UTC sample | Contract | Closed | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---|---:|---:|---:|---:|---:|
| August 2026 | BTCUSDT | 58 | 22.41% | -84.91 | -122.53 | 122.53 |
| August 2026 | ETHUSDT | 62 | 29.03% | -26.91 | -72.98 | 78.85 |
| September–October 2026 | BTCUSDT | 128 | 36.72% | -24.53 | -109.52 | 114.33 |
| September–October 2026 | ETHUSDT | 118 | 36.44% | -17.45 | -105.87 | 110.72 |

## Reproduce

Place the pinned archive as `Scratch/source-2864.md` and the Round 11 Pine
Compat package under `Scratch/priced-runtime`. Use the earlier local Python
AppContainer launcher and denial probe. The staging command verifies the six
official Binance minute ZIPs and checksum files against Round 10 and checks
the four timestamp sequences without filling gaps.
[Round 10 inputs](fmz-round10-magnifier-market.md) · [Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round13_2864_stage Scratch PublicZips research/fmz-round10-magnifier-market.json
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch replay_2864.py probe 90
Scratch/sandbox.ps1 Scratch replay_2864.py '' 840
python -m research.fmz_round13_2864 Scratch Report.json
```

[Verified report and result rows](fmz-round13-2864.json)
