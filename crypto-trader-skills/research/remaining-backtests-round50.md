# Remaining BTC and ETH backtests, round 50

Five entries received verified historical scopes. The backlog falls from 173 to 168. Of the original 785 entries, 336 have verified historical scopes and 281 have verified exclusions. The workbook adds nine performance rows and reaches 5,688 tested catalogue entries.

## Dated BTC inverse reversal cases

The #666 and #667 source runs retain their published one-contract starting size, 20x leverage, 1.5% stop, 3% target and 30-second pause. The study uses the dated BTC-USD-190906 weekly future with a 0.1 BTC wallet and explicit modeled fees. The 15-minute chart and 16-hour test window are research selections. Native marketable fills reconcile to the inverse BTC wallet. The recorded prices are used to check simulated quotes, including the one-tick bid/ask offsets. [Source and reconciliation report](fmz-native-round50-666-667-dated-reversals.json)

| ID and scope | Closed reductions | Gross P&L (BTC) | Settled P&L after fees (BTC) | Terminal marked P&L (BTC) |
| --- | ---: | ---: | ---: | ---: |
| #666 RSI entry | 1 | −0.0001816652 | −0.0001919757 | −0.0003860024 |
| #667 random entry, seeds 0 and 1 | 1 | −0.0001653880 | −0.0001757067 | −0.0003371957 |
| #667 random entry, seed 2 | 0 | 0 | 0 | +0.0000845393 |

The first #666 direction agrees with an independent Wilder RSI calculation using 24 completed 15-minute bars and the opening quote of the next bar. Seeds 0 and 1 generate the same first short and subsequent fills. Seed 2 generates a long that stays open. The dataset establishes the defined historical outcomes for those seeds.

Reproduce the inputs with `python -m research.stage_r50_666_667 FMZ_ZIP ROUND49_AUDIT DATED_1116_MARKET_GZIP PUBLICATION_HTML_DIRECTORY OUTPUT_GZIP`. Name the staged file `round50-666-667-input.json.gz` in the offline FMZ Python AppContainer. Its Python packages must include NumPy and TA-Lib for #666. Run the worker with `(666, 0)` and `(667, 0)`, `(667, 1)`, `(667, 2)`. The third worker argument is `first` or `repeat`. Run `python -m research.fmz_round50_666_667 APP_CONTAINER_ROOT WORKER_PATH OUTPUT_JSON` to repeat the independent accounting.

## #4686 author-named stress day

The archived JavaScript completes the author-named May 19, 2021 China-time ETH perpetual stress day under native simulation. Two runs agree on the source execution and 289 portfolio marks. The scope uses a 1-day chart and 5-minute simulated ticks, with documented reproduction settings for order size, fee and latency. Local simulated depth and fault settings differ from the older displayed author configuration. [Stress-day proof and setup](fmz-native-round55-4686-martingale.json)

| Metric | Verified model value |
| --- | ---: |
| Closed reductions | 26 |
| Closed wins after modeled fees and allocated funding | 26 |
| Gross settled P&L | +2.22605 USDT |
| Settled P&L after modeled fees | +2.10628745 USDT |
| Settled P&L after modeled fees and allocated funding | +2.10459982 USDT |
| Terminal marked P&L including open exposure | −26.12154826 USDT |
| Sampled marked drawdown | 2.64% |

An open 0.205 ETH long and two resting orders remain at cutoff. The separate half-year attempt stops when the source detects simultaneous opposing positions on February 23 at 15:05:00.200 UTC. No half-year performance row is produced.

## #1404 publisher-confirmed Dual RSI direction

The published FMZ backtest shows both long and short fills. The final displayed candle and price peak identify the archived UTC+8 display clock. The causal replay preserves both directions with an explicit Boolean adapter and verifies order chronology and prices against 1m bars. It closes eight BTC and twelve ETH lots. Pooled gross P&L is +347.50 USDT, P&L after modeled fees is −93.52 USDT and P&L after the execution buffer is −317.77 USDT. Three of twenty lots win after modeled costs. The publisher's screenshot accounting has its own reported figures and stays separate from these model results. [Publisher and replay evidence](fmz-round61-pine-rsi-author.json)

## #5773 flat quote and cancellation check

Two preselected 60-second BTC/ETH futures scopes use recorded order books and trade prints. The literal archived script fails during a reporting call. The compatibility setup supplies the flat balance for that log and documented array helpers. All three sell attempts cancel without a fill, and the recorded market remains on the other side of each limit during its lifecycle. The two rows record zero closed P&L and drawdown, with undefined win rates. One-way behavior after a fill remains unverified. [Short-window compatibility evidence](fmz-native-round56-5773-flat.md)

#929 completes its first replay across three seeded wallet scenarios. It remains pending until order and inventory reconciliation and a repeat run are complete. [First-run evidence](fmz-native-round56-929-pending-checkpoint.json)

Delta Demo entry hold is active. The repository suite passed 342 tests and 89 subtests. The workbook verifier compared the previous performance rows, all 173 coverage addresses and new table boundaries.
