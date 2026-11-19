# Manual real-market paper execution test

Three spot-long paper positions are open in ONE10000USDT virtual account. Entries were explicitly requested by the user. All original strategy proposals remained WAIT and are separately archived; none is represented as an automatic breakout signal. Data came from fresh Binance public REST reads without clock overrides.

| Asset | Quantity | Paper fill USDT | Recorded stop | Recorded target |
|---|---:|---:|---:|---:|
| BTCUSDT | 0.03019000 | 63787.16000000 | 63117.72000000 | 65030.40000000 |
| ETHUSDT | 1.07410000 | 1791.94000000 | 1773.12000000 | 1826.88000000 |
| SOLUSDT | 2.05800000 | 72.63000000 | 71.86000000 | 74.05000000 |

Cash:5996.0704159456000000000USDT. Combined entry notional:3999.9296544000000000USDT, capped at4000USDT. SOL is deliberately smaller because BTC+ETH already consume most of this cap.

Snapshot at2026-11-17T19:09:22.939320Z: estimated net unrealized PnL including hypothetical exit costs-10.0076282301000000000USDT. This is a current mark, not realized PnL or a forecast. Fee assumption0.1%per side; adverse slip5bps per side.

Stops and targets are recorded plan levels. No automatic protective-exit watcher or background monitoring is running. Gaps can exceed estimated stop losses. No real exchange orders or money were used.

Complete evidence: execution-result.json, commands.json, trader/ledger.json and per-asset archived market/config/proposal/plan/sizing/risk/order envelopes in assets/.
