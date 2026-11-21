# Remaining BTC and ETH backtests, round 44

Eight strategies received verified historical results. The backlog falls from 201 to 193. Of the original 785 strategies, 316 have verified historical scopes and 276 have source-verified exclusions. The workbook adds 31 result rows and reaches 5,668 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 240 | Using the related FMZ release's valid chart-timeframe setting, the Demark rule matches independent decisions and first Bitfinex opening trades in the original saved window. The malformed saved 18000-minute setting is preserved as a diagnostic. BTC and ETH settle 26 trades for +3,383.01 USD after modeled fees and leave two open. |
| 3664 | Reconstructed FMZ's published 39-minute series from the actual underlying quarter-hour groups. Each value becomes available at its last constituent close. This removes future-volume exposure in the original projection. The causal historical model settles 15 BTC trades across the two tested windows and leaves one open. ETH generates no orders. |
| 3747 | Independent saved Bollinger gates, next opens, equity sizing and 0.1% source commission reconcile across 23 closed lots. The starting and following windows show pooled after-fee P&L of +34.57 and +88.00 USDT. |
| 4142 | The exact zero-deviation identity removes floating-point noise from the pivot rule. Alternate browser cutoff and EMA seed controls produce the same verified order ledger after the correction. The pooled model settles 38 lots for +38,624.55 USDT after modeled fees. |
| 4310 | Both saved Trend-mode runs match 91 closed BTC and ETH lots, all decision gates and the marked account. The modeled execution allowance reduces the two pooled after-fee results to +733.61 and +12,052.49 USDT. One position remains open. |
| 4868 | Used confirmed Cboe VIX release timing and restored the source comparator's documented symmetric crossing behavior. Two closed wins total +1,045.56 USD after fees. Two positions remain open. |
| 5093 and 5094 | Replayed the separate Python and JavaScript source strategies on a documented alternate date with recorded Binance BTC spot depth and signed trades. The original September 5 tape remains unavailable. Zero-fee realized P&L was +47.29 and +109.44 USDT. Applying 0.1% per side gives −434.18 and −1,211.33 USDT respectively. |

Cboe's official put/call records for #4699 and corresponding historical entry prices are now verified. The time the ratios reached the strategy's feed remains unresolved, and the case remains pending. The full-month #3717 synthetic tick simulation is published as supplementary evidence for the previously tested spot-grid strategy. Its hourly drawdown sample and open inventory marks are included in the report.

The workbook lists each run's scope and modeled costs. Delta Demo entry hold is active. The repository suite passed 342 tests and 89 subtests.
