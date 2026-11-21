# Remaining BTC and ETH backtests, round 46

One strategy received a verified historical result. The backlog falls from 187 to 186. Of the original 785 pending entries, 323 have a verified historical scope and 276 have a source-verified exclusion. The workbook adds one performance row and reaches 5,675 tested catalogue entries.

## #5366 minute EMA portfolio

The published Part 4 notebook replays the original 24-market Binance USD-M basket, with 69,660 warm-up minutes and 7,500 execution minutes. Independent archive reconciliation verified 1,851,840 closed minute prices against 72 checksummed Binance files. BTC and ETH contribute 39 and 30 position reductions respectively. The author notebook uses a 0.075% modeled fee per side and executes on candle closes. Its live strategy uses a different asset universe and venue-level execution controls. [Original strategy](https://www.fmz.com/strategy/196784) · [Author notebook context](https://www.fmz.com/bbs-topic/5364)

| Closed-lot metric | Result |
| --- | ---: |
| Position reductions | 1,301 |
| After-fee win rate | 57.26% |
| Gross P&L | +575.63 USDT |
| Allocated fees | 290.32 USDT |
| P&L after fees | +285.32 USDT |
| After-fee drawdown on realized closes | 100.31 USDT (0.97%) |

The terminal 22 open legs remain outside closed P&L. Including the mark and accrued commissions yields +271.15 USDT net and 1.21% marked drawdown. The [result and verification receipts](fmz-native-round50-5366-minute-ema.json) identify all tested assumptions and the script digests.

## Unresolved execution rules

- **#5004.** The primary author declares 10 as initial capital and uses that value in sizing. The FMZ derivative includes a broker-field write of 50,000 that the isolated compatibility parser rejects. On independently reconstructed opening BTC and ETH inputs, the two candidate sizing balances differ by a factor of 5,000 in pre-rounding order quantity. The archived host's balance treatment remains unverified. [Capital evidence](fmz-round58-5004-capital-evidence.md)
- **#5211.** Independent formulas match every indicator and decision checked on 371 daily bars per market. The input contains 106,848 verified five-minute bars per market. Two intrabar paths agree whenever an order is active within each modeled policy. The two BTC position journals agree across all four controls. The final ETH trailing sale of 503.968 ETH differs in price and time when the daily trailing amendment restarts the armed order. The competing fills are 1,622.99 at 02:35 UTC and 1,629.56 at 07:40 UTC on 22 October 2023. Both are diagnostic model events. Original FMZ amendment behavior remains unverified. [Amendment evidence](fmz-round46-5211-amendments.json)

Delta Demo entry hold is active. The repository test suite passed 342 tests and 89 subtests. The two edited workbook tabs were rendered and the workbook comparison verified its prior result rows, all 187 reviewed coverage addresses, and the updated table bounds.
