# Remaining BTC and ETH backtests, round 27

Five more strategies have verified historical replay results. The original 785-strategy backlog has 279 pending. Of the 506 resolved entries, 230 have historical backtests and 276 have source-verified exclusions. The full catalogue has 5,582 tested entries out of 6,184. This round adds 20 result rows to the original `stratergies.xlsx`.

| ID | Historical evidence | Result scope |
| --- | --- | --- |
| 1514 | Native and subsequent windows, Binance spot prices, and a prespecified 32-seed ensemble per market and window | Fixed seed 1 provides the worksheet rows. Short execution is hypothetical on the historical spot tape. The ensemble measures sensitivity to seed on two shared histories. |
| 2401 | Two BitMEX XBTUSD windows with trades, quotes, mark prices, observed depth and funding | One closed lot and one open position per window, in BTC settlement. Both closed lots were negative after costs. |
| 3424 | Official NSE Nifty 50 close and independently verified Binance USD-M 1h and 15m prices | The archived price gates and 14-hour calculation produce a BTC short and an ETH long. Both remain unsettled at every tested availability convention. Separate realized fields include the entry-fee overlay. |
| 5478 | Saved PSAR/EMA source, historical 45m decisions and 5m fills | Three BTC and two ETH closures. One was profitable after fees, with −41.115506745 USD combined after fees. |
| 5755 | Native and subsequent windows with 32 prespecified seeds per market and window | Fixed seed 1 provides the worksheet rows. All 32 combined seed runs were negative after fees in each historical window. |

The 256 stochastic scenario runs span two strategies, two windows, two markets, and 32 seeds. They preserve archived order rules and record the seed in the report. The archived sources leave the seed unspecified. The reported scenarios therefore describe possible historical paths on the same tapes.

The NSE calendar includes the January 20 trading session and the January 22 holiday. The benchmark makes each daily close available at 11:00 UTC on its session date, with 10:00 UTC and the next 00:00 UTC as timing checks. The historical FMZ publication time is unavailable. The strategy uses the Nifty 50 closing index value. [NSE calendar circular](https://nsearchives.nseindia.com/content/circulars/CMPT60343.pdf) · [TradingView historical data timing](https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/)

The coverage JSON binds all 284 opening backlog entries to their source and status, and records the four report digests. Workbook verification compares all 20 added rows against their reports, the amended catalogue cells against the coverage ledger, and the unchanged workbook content against the previous Git checkpoint. Delta Demo entry hold is active.
