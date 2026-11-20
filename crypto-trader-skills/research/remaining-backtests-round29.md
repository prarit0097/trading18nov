# Remaining BTC and ETH backtests, round 29

Three more strategies have verified historical replays. Of the original 785 pending entries, 274 remain, 235 now have historical backtests, and 276 have source-verified exclusions. The original `stratergies.xlsx` has 15 additional result rows and 5,587 tested entries across the full catalogue.

| ID | Replay scope | Historical result |
| --- | --- | --- |
| 134 | January 2024 Binance USD-M. Unchanged Pine v4 logic with Heikin Ashi signals, raw 30m prices, and an independent one-minute bracket check. | All 87 order events agree. 52 closed lots, 34 after-fee winners, 4,031.07 USDT combined after source commission, and one ETH position open. The deep realized drawdown and authored base-unit exposure limit what this benchmark implies. |
| 4483 | Saved and next equal BTCUSDT and ETHUSDT windows. The source retains order-fill callbacks. Each 1h observation exposes its open or completed close at its actual event time. | 87 closed lots across both windows. Independent source signals, sizing, fees, event arrival and equity reconcile. The benchmark supplies a causal hourly event schedule. |
| 4618 | Two sampled BitMEX XBTUSD sessions with three prespecified seeds on each. Observed price and depth are checked for every order under the zero-added-delay model. | 18 winners after fees among 2,884 closed lots. All six scopes lost money after fees. The separate 100 ms check found price or size failures in five scopes. |

The #134 source does not specify a saved exchange window. The report identifies the benchmark and its cold chart initialization. It records the supplied 0.04% per-side commission and fill model. Additional spread, funding, margin and liquidation effects are outside this replay.

The #4483 report preserves a diagnostic that reproduces the historical daily-bar callback lookahead. Only the hour-by-hour causal runs provide workbook result rows. The #4618 report includes all six prespecified zero-delay paths and records the separate 100 ms sensitivity.

The candidate workbook was checked against the preceding checkpoint and all three source-bound reports, including catalogue statuses, the complete result table, native BTC precision and untouched sheets. Delta Demo entry hold is active.
