# Remaining BTC and ETH backtests, round 47

Two strategies received verified historical results and five received source-verified exclusions. The backlog fell from 186 to 179. Of the original 785 entries, 325 have verified historical scopes and 281 have verified exclusions. The workbook adds seven performance rows and reaches 5,677 tested catalogue entries.

## Verified historical replays

| ID | Historical scope | Closed lots | After-fee P&L | P&L after modeled costs | Realized max drawdown after modeled costs |
| --- | --- | ---: | ---: | ---: | ---: |
| 3184 | Saved FMZ BTC dates, with ETH under the same settings | 71 | +253.58 USDT | −351.81 USDT | 3,311.41 USDT |
| 3184 | Immediate 30-day BTC/ETH follow-up | 3 | −1,393.94 USDT | −1,472.11 USDT | 2,163.58 USDT |
| 4850 | Named Binance COIN-M BTCUSD_211231 quarter, 1 October to 24 December 2021 | 6 | −0.0072221682 BTC | −0.0072221682 BTC | 0.0072221682 BTC |

- **#3184.** The authored ternary calls the low-fractal function conditionally. The adapter preserves the local history of successive calls under Pine v4 semantics. Independent gates and quote checks reconcile all 148 fills across BTC and ETH. The default external series is inactive in the tested order path. The pooled after-cost win rate on the saved dates is 62/71, or 87.32%. Closed P&L is negative after the modeled execution buffer, and no position remains open at either cutoff. [Execution evidence](fmz-round58-pine-cipher-divergence.json)
- **#4850.** The original Python executed unchanged using FMZ's native simulator. The research case selects a named 100 USD inverse BTC quarter, 0.1 BTC starting collateral and explicit maker/taker fees because the archive supplies no saved deployment configuration. The native and instrumented runs agree on 21 filled orders and all 85 wallet snapshots. All six realized reductions are losses. A 20-contract short remains open at cutoff and its mark is reported separately. The simulator generates intrahour ticks from the official archived hourly feed. [Inverse ledger and source receipts](fmz-native-round51-4850-inverse-quarter.json)

## Scope and data findings

- #391 trades LTC as the base asset at fixed LTC/BTC thresholds. #405 targets the HUSD/USDT peg and Huobi's zero-fee promotion. #1392 fixes the instrument and price bounds to HT/USDT. #1017 and #1021 route externally chosen orders and provide no signal rules. Their original sources and pinned checks are recorded with the exclusions. [Scope evidence](fmz-round47-scope.json)
- #1384's published default is 200, and its documented case is the November 2021 Binance DAR launch. It remains pending for a BTC/ETH case with a verified first tradable ticker and execution inputs. [Binance listing notice](https://www.binance.com/en/support/announcement/detail/28c68286fe9340cd97740774b4e13af9)
- #694 now has all 466,560 authored one-minute bars per market for BTC, ETH and LTC spot, plus one warm-up day. FMZ serves them under its current OKX market identifier. There are 561, 1,322 and 5,819 zero-volume minutes respectively. Native 500 ms polling, resting-order fills and the three account ledgers still require independent checks. [History and coverage receipts](fmz-round47-694-market-evidence.json)

Delta Demo entry hold is active. The repository test suite passed 342 tests and 89 subtests. Workbook verification compared all prior backtest rows, the updated table range and all 186 coverage addresses. The two edited tabs were rendered for visual verification.
