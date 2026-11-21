# FMZ #5091 recorded spot replay

The archived LeeksReaper Python source uses trade prints, the top three book levels and account inventory to drive its ladder, cancellations and burst entries. Three probes on the saved March 28, 2022 date returned empty real-tick data for BTC/USDT and ETH/USDT. The minute endpoint returned candles, while the original source selected real-tick mode. [FMZ source](https://www.fmz.com/strategy/354232) · [FMZ real-tick rules](https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching)

The two alternate windows ran from 12:00 to 12:20 UTC on October 1 and November 19, 2026. Both replayed the exact Python source on BTC/USDT and ETH/USDT together in the pinned official offline engine. The two sessions contain 67,339 recorded market events plus preload. The local callback supplies recorded trade prints and five depth levels per market. Source calls run in the original order with no additional broker queries. [Official Python engine](https://github.com/fmzquant/backtest_python)

Both simulated accounts start with 10,000 USDT. The original BTC configuration sets zero starting BTC and zero fees. The original ETH configuration omits these settings, so the official loader supplies 3 ETH and a 0.015% maker and 0.02% taker fee. The earliest ETH basis is the last actual bid before the session. The 0.001 ETH balancing buy requests were below the 5 USDT minimum. The November ETH sell filled as a taker.

| UTC date | Market | Settled sales | Gross USDT | After fees USDT | After-fee settled drawdown USDT |
|---|---|---:|---:|---:|---:|
| 2026-10-01 | BTCUSDT | 0 | 0 | 0 | 0 |
| 2026-10-01 | ETHUSDT | 0 | 0 | 0 | 0 |
| 2026-11-19 | BTCUSDT | 1 | -0.32557240 | -0.32557240 | 0.32557240 |
| 2026-11-19 | ETHUSDT | 1 | -7.49952000 | -8.12263334 | 8.12263334 |

The November sales both realized losses. Zero-sale win rates are undefined and remaining inventory is outside the settled metrics. A 77-second replay matched the full source call sequence through both November sells. Native wallet changes at 100 ms resolution identify the first three BTC prices and verify the sale's FIFO basis. The recorded tape contains the two reported sale prices in their matching intervals. These are results from two short historical sessions.

## Reproduce

1. Run the stage script with `ARCHIVED_MARKDOWN APP_CONTAINER_ROOT 2026-10-01`, then with `2026-11-19`. This fetches and validates the public event files before isolation.
2. Place the runner in the existing FMZ Python AppContainer and run it for each full date. Run it again with arguments `2026-11-19 100 77` to reproduce the early source reads and wallet snapshots.
3. Run the report validator with `APP_CONTAINER_ROOT OUTPUT_JSON`. Source, market and runtime hashes are in the resulting JSON. Keep raw event files and engine files outside Git.
