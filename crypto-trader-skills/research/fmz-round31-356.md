# FMZ #356 EtHEriOOOm 30-minute historical comparison

The archived source omits its Pine version directive and saved backtest
settings. Its input declarations require the legacy Pine v4 API. The
portable comparison restores that version directive. Both archived
numeric directions produce the same observed signals, orders and trades
as explicit long and short directions. BTC and ETH are tested at the
30-minute timeframe in the strategy title, from January 1 through February
1, 2024 UTC exclusive. Each market uses 1,488 decision candles aggregated
from 2,976 official Binance USD-M candles.
[Pinned FMZ archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/EtHEriOOOm-30MIN.md) · [FMZ strategy page](https://www.fmz.com/strategy/376259) · [Binance public market archives](https://data.binance.vision/)

The archived default uses the prior confirmed 30-minute close for its
Jurik calculation. Its TWAP timestamp request also selects the chart
timeframe at the saved input default. The audit checked both series
across all 1,488 candles on each market. The authored group of trend and
volume filters and shared entry gate remain active. The original long
and short order conditions drive next-open market entries and
reversals. The stop and target take percentages of the decision close
and use those distances from the position's entry fill.
[Legacy market and bracket behavior](https://www.tradingview.com/pine-script-docs/v4/essential/strategies/)

The audit checked 33 brackets and 17 reversals against every matching
official Binance one-minute candle. Every close matches the full
30-minute price path and the first eligible minute. No bracket reaches
both price levels in the same chart candle. Each fill is on its
contract's price grid. Next-open quantity, reversal transaction size,
costs and the end position also reconcile.

| Market | Closed | After-fee win rate | Gross USDT | After-fee USDT | After-fee drawdown USDT |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 25 | 56% | −1,554.55 | −1,739.23 | 1,739.23 |
| ETHUSDT | 25 | 76% | 2,003.81 | 1,793.46 | 891.76 |
| Pooled | 50 | 66% | 449.26 | 54.24 | 1,916.30 |

The model starts each asset with 10,000 USDT, sizes at 100% of next-open
equity in 0.001-unit steps and charges the author's 0.04% commission on
each execution side. Gross P&L removes those commissions from the same
lots. Realized drawdown and P&L exclude one open short per market.
The replay models candle fills and the declared zero slippage. FMZ host
settings, order-book queues, spread and funding are outside this scope.
[FMZ execution settings](https://www.fmz.com/doc/9293#strategy)

## Reproduce

Use the already verified Round 30 January Binance files and isolated
Pine Compat runtime. Copy the hash-pinned FMZ document to
`PyScratch/source-356.md`. The Round 30 staging command supplies the
compared chart and data receipt names, and both reports use the same
actual-minute archives under PublicInputs.
[Round 30 January data and runtime procedure](fmz-round30-1070.md)

```powershell
python -m research.fmz_round30_1070_stage PublicInputs PyScratch
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round31_356_runner.py PyScratch/probe_356.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 45
PyScratch/sandbox.ps1 PyScratch probe_356.py '' 120
python -m research.fmz_round31_356 PyScratch PublicInputs Report.json
```

[Verified 30-minute comparison and cost evidence](fmz-round31-356.json)
