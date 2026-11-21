# Remaining BTC and ETH backtests, round 42

Six strategies received verified historical results. The backlog falls from 212 to 206. Of the original 785 strategies, 303 have verified historical scopes and 276 have source-verified exclusions. The workbook adds 24 result rows and reaches 5,655 tested catalogue entries.

| ID | Verified historical scope |
| --- | --- |
| 3689 | Causal 5m and 1m replay agree with the source's journal after guarding four inactive exit calls. The independent ledger reproduces 109 closes across the saved and following windows. The saved pooled result changes from +$515.82 after fees to −$690.68 after the modeled execution allowance. The source uses a fixed-unit simulation without margin. |
| 4063 | The saved quarterly setting uses prices before they are available. The strategy's own lookahead-off option produces two closed trades for −16,071.77 USDT after fees and two open positions. Saved-default future-price diagnostics are retained in the evidence. |
| 4802 | The author-supported public hashrate variant uses Blockchain.com estimates verified against Coin Metrics. Both feeds reproduce the same crosses with a one-day publication lag. The two windows close 20 BTC and ETH lots, with pooled after-fee results of +1,413.21 and −5,603.98 USDT. The archived IntoTheBlock feed remains unavailable. |
| 4881 | The archived capital declaration and the later capital assignment conflict. All tested capital readings produce the same trades because the risk triggers remain outside the observed minute price range. A fill callback used an unavailable hourly close, so the verified replay waits for the actual close. It settles 25 trades for −3,240.45 USDT after fees. |
| 5114 | The source's USD conversion map omits USDT. Its empty-symbol request resolves to the chart price. All 24 independently verified breakouts size to zero after flooring, and the historical run opens no positions. The completed-trade win rate is unavailable. |
| 5646 | Retained the authored constant high and low inputs to the stochastic formula. Providing the optional annual series, removing the disabled pivot, and disabling fill callbacks give the same trade journal. Official minute and quarter-hour candles agree on all hourly open, high, low and close values. The replay closes 17 trades for +127.13 USDT after fees and leaves two open. |

Win rates and drawdowns use completed trades. Source and market receipts, model assumptions, and positions at cutoff are recorded in the evidence. Delta Demo entry hold is active. The repository suite passed 342 tests and 89 subtests.
