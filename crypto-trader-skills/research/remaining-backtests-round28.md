# Remaining BTC and ETH backtests, round 28

Two more historical replays reduce the original backlog from 279 to 277. Of the original 785 strategies, 232 have historical backtests and 276 have source-verified exclusions. The workbook has 5,584 tested catalogue entries and six new performance rows.

| ID | Historical evidence | Outcome |
| --- | --- | --- |
| 1003 | Saved 1h decisions, 30m request context and 15m price evidence for BTCUSDT and ETHUSDT, with archived short mode enabled | No entry or cash change. The source comparison across a missing-to-present session value never starts the range. An explicitly guarded reset generates orders and is recorded separately as a sensitivity check. |
| 5398 | Exact archived source and historical Binance ETHUSD_211231 market quotes, trades and mark prices for three predeclared sessions | One November short closed at −0.001729432124 ETH before fees, with 0.000047435240 ETH in fees and −0.001776867364 ETH net. One long remained open. The archive leaves the venue unspecified, so the identified Binance quarterly contract is a compatible historical benchmark. |
| 3952 | Active confidence signal uses a daily close under Pine v2 lookahead semantics | Five pre-close BTC/ETH entries change under confirmed-only timing. The strategy remains pending, and the diagnostic replays supply no workbook performance rows. |

The candidate workbook was checked against the source-bound coverage manifest and the preceding workbook. It preserves the table, historical result rows, and all out-of-scope sheet content. The Delta Demo entry hold is active.
