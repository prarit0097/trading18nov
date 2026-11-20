# Remaining strategy backtests · Round 24

Four measured strategies add 18 workbook rows. The original 785-ID queue has 297 pending and 488 resolved. The catalogue has 5,564 tested entries.

- FMZ #5441 used a causal variant on the archived daily dates. The source reads weekly and monthly closing prices before those periods end. The variant uses the completed daily close as the observable period-to-date price and retains the original period opens, completed-period EMAs and bracket setting. The change altered an ETH entry gate and its bracket. Complete Binance hourly prices verified all five realized exits. [Timing and fill proof](fmz-round24-5441.json)
- FMZ #1073 restored the source's commented strategy declaration, including its fixed-cash sizing and 0.025% commission. The remaining program matches the related WaveTrend source. The replay respects the saved final-minute cutoff and verifies 123 closed lots and two ending open positions. [Restoration and market checks](fmz-round24-1073.md)
- FMZ #409 retained the older platform's numeric long-direction convention with an isolated native control. Its 57 closes use an explicit Bitfinex USD comparison because the archive supplies no saved venue or cadence. FMZ #4755 independently verified three closes using only completed monthly reference values. [Confirmed prices and direction evidence](fmz-round24-pine-confirmed-price.json)
- FMZ #117 and #3854 remain pending. The first still needs its archived external signals. The second now has pinned framework and plotting dependencies, with deployment and fills unresolved. [Framework sources](fmz-native-framework-provenance-round24.json)
- FMZ #2490 remains pending. Historical book levels and the original one-second wait established an initial 100-contract fill and one short round trip. Later order remainders need evidence to verify either complete window. [Execution sequence](fmz-native-okex-swap-fill-bindings-round24.json)

The workbook preserves all prior coverage and result rows. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round24-coverage.json)
