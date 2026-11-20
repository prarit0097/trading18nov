# FMZ #5006 GBP-account replay

The archived RSI versus SMA strategy uses Binance USD-M BTCUSDT on a
10-minute chart. Its default inputs calculate eight-period Wilder RSI
from the open, center that RSI at zero, and smooth it over 34 bars.
Changes in the smoothed signal's sign send the corresponding market
entry and close the opposite position. The ETHUSDT runs apply the same
settings on a second contract. Each run uses the archived GBP account
currency, the runtime's default £1 million capital and 10% equity sizing.
[Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E7%A7%BB%E5%8A%A8%E5%B9%B3%E5%9D%87%E4%B8%8E%E7%9B%B8%E5%AF%B9%E5%BC%BA%E5%BC%B1%E6%8C%87%E6%A0%87%E7%AD%96%E7%95%A5Moving-Average-Relative-Strength-Index-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/433547)

The exact archived Pine v2 body supplies the performance data. Its
default trailing branch supplies `trail_points` with no offset. Those
calls emit entry diagnostics. A v2 control removes that branch and a
v5 control also updates typed inputs and namespaces. Both reproduce the
original plots, orders, position, equity and closed trades. An independent
calculation verifies both Wilder averages, RSI, the SMA, every direction
and the market order sequence. The four windows contain 26,496 ten-minute
bars, 1,298 fills, 647 closed trades and four ending open positions.
[TradingView v5 exit migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#strategyexit-now-must-do-something)

The quote check reconstructs each chart candle from checksummed Binance
one-minute candles and matches every fill to the first minute open. The
GBP model translates USDT using the last completed UTC day's Kraken
USDTGBP close. The data preparation selects 93 fixed effective dates and
omits subsequent candles and the API's active incomplete candle. The
archived strategy has zero commission. The fee sensitivity uses 0.075%
per side on the same verified fills, with fees translated at their own
execution-date rates. P&L and drawdown in the table are realized GBP.
[Kraken OHLC documentation](https://docs.kraken.com/api/docs/rest-api/get-ohlc-data/) · [Kraken daily rate input](https://api.kraken.com/0/public/OHLC?pair=USDTGBP&interval=1440&since=1785456000) · [Binance public archive](https://data.binance.vision/)

| UTC sample | Contract | Closed | After-fee win rate | Gross GBP | After-fee GBP | After-fee drawdown GBP |
|---|---|---:|---:|---:|---:|---:|
| August 2026 | BTCUSDT | 110 | 39.09% | -16,780.96 | -33,226.88 | 33,349.03 |
| August 2026 | ETHUSDT | 116 | 52.59% | -1,517.36 | -18,960.14 | 26,847.44 |
| September–October 2026 | BTCUSDT | 208 | 52.88% | 12,114.17 | -19,285.24 | 24,041.42 |
| September–October 2026 | ETHUSDT | 213 | 50.70% | 1,541.81 | -30,598.23 | 35,664.74 |

## Reproduce

Prepare the four Round 10 60-minute feed envelopes with 10-minute data and
the four Round 13 one-minute input files. Use the pinned Round 11 Pine Compat
package, Python AppContainer launcher and isolation probe. Put the archived
Markdown in `Scratch/source-5006.md`. Fetch the Kraken response to a
local file and generate the canonical rate slice before the offline run.
[Round 10 feed preparation](fmz-round10-magnifier-market.md) · [Round 13 minute inputs](fmz-round13-2864.md) · [Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round16_5006_fx KrakenDaily.json Scratch/5006-kraken-fx-rates.json
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round15_3604_runner.py Scratch/probe_3604.py
Copy-Item research/fmz_round16_5006_runner.py Scratch/probe_5006.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch probe_5006.py '' 240
python -m research.fmz_round16_5006 Scratch research/fmz-round13-2864.json Report.json
```

[Verified results and fill checks](fmz-round16-5006.json)
