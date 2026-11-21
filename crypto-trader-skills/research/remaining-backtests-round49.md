# Remaining BTC and ETH backtests, round 49

Five strategies received verified historical results, bringing the backlog from 178 to 173. Of the original 785 entries, 331 have verified historical scopes and 281 have verified exclusions. The workbook adds 14 performance rows and reaches 5,683 tested catalogue entries.

| ID | Verified historical scope | Result |
| --- | --- | --- |
| 258 | Unchanged canonical JavaScript Dual Thrust on the named BTC-USD-190906 current-week expiry. Selected 1 September 2019, 06:00–22:00 UTC, 1h decision bars, 0.1 BTC collateral, and modeled fees. | Nine simulated fills and four reductions. Realized P&L after modeled fees −0.0001939310 BTC, with one long contract open. An uninstrumented control matches the order journal and all 193 portfolio marks. |
| 694 | Saved 2019–2020 BTC/ETH/LTC spot setup, official FMZ OKX feed and unchanged strategy. Native time and the authored 500 ms sleep govern polling. | Across 653 filled orders, 301 sales close FIFO lots. Portfolio settled P&L +15,585.81 USDT, with three funded inventories remaining. BTC and ETH alone close 174 sales, with 79 after-fee wins (45.40%), +15,588.92 USDT settled P&L and 11,155.96 USDT max realized drawdown. |
| 1045 | BTC/ETH adaptation of a CSI 300 linear SVR notebook. Uses the authored 20 lagged closes and 1,500 training rows, then evaluates previously unseen 2024 outcomes. Entry uses an explicit 01:00 UTC delayed fill and exit uses 23:00 UTC. | 337 closes, 47.48% after-cost win rate, +201.01 USDT gross, −153.96 USDT after fees, −334.45 USDT after execution buffer, and 29.11% max realized drawdown. |
| 5091 | Exact spot ladder code with recorded order book and trade events, on two selected 20-minute dates. The original 2022 real-tick archive did not return market records. | Two October market rows carry zero closes. The November BTC and ETH rows each close one loss, −0.32557240 USDT and −8.12263334 USDT after simulated fees. The workbook records unresolved inventory separately. |
| 5193 | Saved fixed BTC weekly grid limits, one contract per level, bids 100 to 91 USD, tested on the named 2019 expiry in an explicitly funded 2 BTC scenario. | Native engine accepts ten resting bids and repeats all order states and wallet marks. Observed tape lows stay above every bid and zero orders fill. P&L and drawdown are zero, with win rate undefined. |

## #694 accounting and reproducibility

Both isolated full replays agree on every order, wallet and clock witness, including the run with original logging. All 653 model fills are at source limits inside positive-volume placement candles. Separate passive and marketable control orders produce 0.015% maker and 0.02% taker fees. Native cash and inventory for all three portfolios reconcile to the maker rate across the replay. Final candle marks remain separate from realized P&L. Seeded inventory uses the native opening mark as cost basis. Realized drawdown uses order placement time and the independent FIFO book. [Native spot ledger](fmz-native-round49-694-spot-portfolio.json) · [Official feed receipts](fmz-round47-694-market-evidence.json)

To recreate the staged runner input, place the 72 checksum-matched market chunks and the three checksum-matched readback tail packets in a local directory, named by base asset and first Unix second such as BTC-1550534400.json. Run `python -m research.fmz_round49_694_stage FMZ_ZIP MARKET_MANIFEST TAIL_MANIFEST PACKET_DIRECTORY OUTPUT_GZIP`. Name the staged file `round47-694-full.json.gz` inside the existing offline FMZ Python AppContainer. The source worker emits the native replay receipt. Check the decompressed digest across staged archives. The verifier reads that input, the two logged and muted full run receipts, the two fee fixtures, the worker and the market manifest. [Readback tail receipts](fmz-round49-694-tail.json)

The original SVR solver exceeded its time cap. The convex solver uses the same epsilon-SVR objective and an independent primal–dual solution check. The workbook names #1045 as a causal adaptation and uses that solver result. [SVR holdout and solver verification](fmz-round60-svr-notebook.json)

## Remaining dependencies

Four Pine cases require verified oil or natural gas history with the intended market session. Two also contain only a commented strategy declaration. The dated FXCM and Dukascopy checks are recorded in the evidence. #4429's default basket uses BTC only as a benchmark, and a two-member BTC/ETH basket makes the archived normalization undefined. A larger source-compatible basket with synchronized executable quotes remains open. [Commodity dependencies](fmz-round59-pine-commodity-dependencies.json) · [Basket evidence](fmz-round60-4429-universe-evidence.md)

Delta Demo entry hold is active. The repository test suite passed 342 tests and 89 subtests. Workbook verification checked prior backtest rows, all 178 coverage addresses and the updated table boundary.
