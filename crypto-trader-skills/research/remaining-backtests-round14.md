# Remaining strategy backtests · Round 14

This pass tested six new strategy IDs and added 32 result rows. Five IDs produced closes. Six other IDs were resolved through archived source review. The original 785-ID queue has 373 pending and 412 resolved. The full catalogue has 5,509 tested entries.

## Historical results

- FMZ #108, #351 and #2434 preserve the published daily Supertrend, weekly Hull and chart-context DEMA references. Both execution backends and independent historical signal and fill checks agreed on 106 closed lots. [Native reference evidence](fmz-round14-pine-native-refs.json)
- FMZ #1214 reproduced the effective authored v4 reversal logic in both v4 and v5 over 264,960 historical minute bars. The four parameter-free exits have no valid price or trailing instructions. The migration removes those calls and reproduces 1,750 closed positions under the archived commissions. Both positive and negative historical windows appear in the workbook. [Legacy reversal evidence](fmz-round14-1214.md)
- FMZ #1091 uses all nine values recovered from the public author form. The BTC-only initialization guard remains in force. It samples orders every 24 hours at observed Binance opens, using 199 closed candles and the current open for the harmonic mean. The 2018–2021 window produced 68 reduction orders and 345 matched FIFO allocations. The subsequent equal-length window had purchases without sales. Daily marked drawdown after modeled costs was 63.35% and 28.88%, respectively. The workbook win rate and drawdown columns measure realized results on closed lots. [AHR999 evidence](fmz-round14-ahr.json) · [Author settings](https://www.fmz.com/strategy/299799)
- FMZ #5197 ran the original hourly synthetic-tick order handling at the archived 20× margin. Across four isolated BTC/ETH runs, the source canceled all 26,874 resting orders after 1.3 simulated seconds each. The four wallets, accepted fees and positions remained flat, which gives no realized win rate. [Native cancellation evidence](fmz-native-martingale-no-fills-round13.json)

## Source review

Five records were classified from their pinned source as API examples, one-shot tools or scripts without an active entry. FMZ #4632 cannot produce an order in its published form. Its account-value path reads a value property from a numeric or string value, making the allocation predicates compare with NaN. That result reproduces across one exchange and two exchange-account layouts. The distinct #4628 teaching implementation still needs the configured basket and shared BTC balance semantics. [Source records](fmz-round14-source-roles.json) · [Index balance controls](fmz-native-index-balance-source-round13.json)

## Verification

The repository suite passed 340 tests and 89 subtests. The workbook validation checks every added result, all 385 carried-forward candidate statuses, the result table range and formatting. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round14-coverage.json)
