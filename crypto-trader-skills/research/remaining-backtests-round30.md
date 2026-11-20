# Remaining BTC and ETH backtests, round 30

Four verified replays reduce the original backlog from 274 to 270. Of the 785 original entries, 239 have historical backtests and 276 have source-verified exclusions. The original `stratergies.xlsx` contains 18 additional result rows and 5,591 tested catalogue entries.

| ID | Test scope | Result |
| --- | --- | --- |
| 939 | Saved BTC/ETH 4h markets and the subsequent equal-length windows | The archived nested request uses prior daily values. Independent indicators and two execution backends match all 823 closed lots. |
| 1070 | January 2024 Binance USD-M BTC and ETH, using the source's Pine v4 limit precedence and executable tick prices | 179 closed lots, 101 after-fee winners and −3,597.44 USDT combined net. Two positions remain open. A separate literal replay records 76 off-grid fills. Exact FMZ host configuration and average-price behavior remain unresolved. |
| 2521 | Saved December 2023 one-minute window and ETH comparison, with prior-day USD conversion | 194 closed lots and −152.34 USD after the fee overlay. The sizing declaration remains USD 662 with 100% equity allocation. |
| 4648 | Saved daily window and a separate replay with read-only pre-window price history | With 30 cold chart bars, no score reaches its 188-bar lookback. The warm-up sensitivity records one BTC close and two ending open positions. |

For the two legacy momentum scripts, the USD 50,000 assignment appears in the reporting tail. The verified runners preserve the authored USD 662 trading declaration and independently check order signals, opening prices, quantities, closed gross P&L and USD marks. Fee overlays and read-only warm-up assumptions are included with the results.

The original workbook is verified against all three report digests, catalogue statuses and the preceding workbook. Delta Demo entry hold is active.
