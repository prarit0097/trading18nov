# Native FMZ JavaScript spot replay

Two archived strategies completed on both BTCUSDT and ETHUSDT Binance spot simulation markets. ID 476, KingKeltner, opened a BTC lot in each window and had no closed lots. ID 597, the single moving-average trend strategy, closed 169 BTC lots in Reference and 51 in Later. ETH had no fills for either strategy. The manifest also records specific dependencies for the other seven screened IDs. [Native result and order evidence](fmz-native-spot-replay.json)

The native FMZ WASM engine uses 15-minute charts from five-minute public Binance spot candles served by FMZ. Reference runs from 23 September through 20 October and Later from 21 October through 3 November 2026, in IST. The inputs include 900,000 seconds of native pre-roll, before any strategy order can be placed. The engine's configured end extends by five minutes so the worker can retrieve a final state before the engine raises EOF. The worker stops strategy execution at the last scheduled sleep before the ten-second settlement boundary, records the final state in the last minute and checks that no orders are resting. All order timestamps precede the exclusive period end. [Offline engine probe](fmz-native-engine-probe.md)

The two original scripts use explicit constants and the chart's configured timeframe. The setup uses 10,000 USDT and zero starting inventory. It binds the retired `GetMinStock` API to the market's actual minimum base quantity from the public feed. Price precision is 0.01 USDT for both markets. Minimum base quantity is 0.00001 BTC and 0.0001 ETH. The native matching engine uses its candle-derived ticks and each source's own order prices and sizes. [FMZ minimum quantity behavior](https://www.fmz.com/strategy/30861) · [FMZ symbol conventions](https://www.fmz.com/syntax-guide/conventions/symbol)

The worker paginates order history and reconciles filled quantity, average price and 5.9 basis points of fees per side against the engine's ending cash and inventory. A canceled unfilled order contributes zero. The closed-lot metrics use first-in, first-out matching and the order's reported placement time for realized drawdown sequencing. Native trade fees are included in the after-fee panel. The net panel also deducts a 3-basis-point-per-side spread and slippage estimate. Open lots count as unsettled and contribute no realized P&L. The result manifest embeds the native orders and independent ledger differences. [FMZ order-history arguments](https://www.fmz.com/syntax-guide/fun/trade/exchange.gethistoryorders)

## Reproduce

Use the pinned FMZ catalogue ZIP described in the [Pine catalogue replay](delta-pending-catalogue-replay.md). `prepare` extracts source code, downloads and checks the pinned official engine, adapts the callback to use public local data, and validates candle coverage. For reproducibility, preserve the downloaded response bodies because their service timing metadata can vary across requests.

```powershell
python -m research.fmz_native_spot_replay prepare "$scratch/fmz.zip" "$scratch/native-spot"
```

Run `spot-replay-paged.cjs` from the scratch directory in the verified no-network Windows AppContainer with the host time zone set to IST. Launch Node with `--preserve-symlinks --preserve-symlinks-main --permission` and read and write permissions restricted to the scratch directory. Node v24.18.1 produced `spot-replay-paged.json` in that directory. Then validate the orders and generate the report from the repository root.

```powershell
python -m research.fmz_native_spot_replay finalize "$scratch/fmz.zip" "$scratch/native-spot" research/fmz-native-spot-replay.json
```
