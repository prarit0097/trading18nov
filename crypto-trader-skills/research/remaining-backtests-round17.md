# Remaining strategy backtests · Round 17

Eight historical tests added 47 workbook rows. Six IDs produced closed events or lots. The KuMEX and daily accumulation studies had ending positions and zero closed trades. The original 785-ID queue has 351 pending and 434 resolved. The overall catalogue has 5,531 tested entries.

## Replay evidence

- FMZ #3027, #5454 and #5591 executed the archived fractal, EMA/RSI and net-volume orders. Both execution backends and independent ledgers agreed on 1,349 closures. The Pine migrations preserve effective order instructions and document the parameter-free exit calls that have no order effect. [Legacy entry studies](fmz-round17-pine-legacy-entries.json)
- FMZ #2794 and #2796 use the restored QQE declarations, archived defaults and distinct saved date windows. The replay verifies comparative rising and falling behavior against each preceding sample as documented by FMZ. Independent arithmetic confirms 61 closures. [QQE source and fills](fmz-round18-pine-qqe.json)
- FMZ #4671 retains the archived v4 session filters and 66-tick stops. The standalone declaration uses the 50,000 capital literal. Restoring the inactive 10,000 declaration reproduced the fills as a separate sensitivity. Six runs closed 28 lots, with 27 stops independently confirmed against the corresponding 15-minute prices. [Session replay](fmz-round17-4671.md)
- KuMEX #4383 uses public quote events, mark prices and funding for four BTC and ETH inverse contract cases. Each eight-hour scope filled one initial short and had zero realized closes. The archived driver reads the position P&L ratio. The official API distinguishes that field from leveraged return on equity, which was replayed as a sensitivity. The report separates realized results and marked open positions. Workbook rows keep native BTC and ETH settlement units. [Inverse contracts and reconciliation](fmz-kumex-dca-round17.json)
- FMZ #4795 uses the one-USDT default from its public author form. MEXC permits this submitted size on both spot pairs. Two 14-day opening-price replays per market verified 56 modeled purchases and ending inventory. The source has no sale rule. Marked P&L and daily marked drawdown appear in the evidence. [MEXC replay](fmz-round17-mexc-dca.json) · [Venue minimum announcement](https://www.mexc.com/announcements/article/announcement-on-the-adjustment-to-the-minimum-order-amount-for-spot-trading-pairs-17827791517449)

## Source extraction verification

The shared Pine extractor now preserves line comments and quoted strings while removing real block comments. Two regression cases reproduced the previous damage and pass with the corrected extractor. In 5,283 archived Pine documents, 52 blocks changed at the text level. Exact executable lines, indentation and directives matched for all 44 previously tested cases among those blocks. Four pending cases had restored executable material. The two QQE replays are complete here. #3742 and #5457 retain the new source-specific blockers. [Catalogue comparison](fmz-round17-pine-comment-audit.json)

The repository suite passed 342 tests and 89 subtests. The workbook validation covers the result rows, the 359 prior candidate statuses, native settlement precision and the full table range. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round17-coverage.json)
