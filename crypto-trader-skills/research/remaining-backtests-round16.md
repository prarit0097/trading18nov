# Remaining strategy backtests · Round 16

Seven historical tests added 39 workbook rows. Six IDs produced 1,292 unpooled closed lots, and the archived fixed-clock study recorded zero fills. The original 785-ID queue has 359 pending and 426 resolved. The overall catalogue has 5,523 tested entries.

## Historical results

- FMZ #2534 executes the authored prior-five-hour breakout and EMA10/21 orders together. Both Piner backends and an independent account ledger verified 450 closes under the archived 100%-equity sizing and 0.2% commission per side. [Breakout and EMA evidence](fmz-round16-pine-breakout.json)
- FMZ #494, #5010 and #5047 preserve their original LowPass or EMA selector defaults. The one-unit versions retain their authored long-only direction. The native and follow-up cases produced 187 independently verified closures. [Filter and fill evidence](fmz-round17-pine-emperor.json)
- FMZ #5006 preserves the original Pine v2 entry and exit behavior. The GBP ledger uses observed Kraken USDT/GBP rates from the prior completed UTC day. Its 1,298 orders reconcile to official Binance one-minute opens, producing 647 closures. Workbook values for these rows explicitly carry the GBP label. [GBP replay evidence](fmz-round16-5006.md)
- FMZ #5411 fixes the historical runtime clock to the archived December 2024 end, interpreted as UTC. Each tested market submits 30 limits. All 29 subsequent observed daily lows in each market remain above their working limit. The remaining order is outside the sampled exit horizon. Positive controls separately verify fills at valid limits. [Clock and broker controls](fmz-round16-5411.md)
- FMZ #5617 uses monthly Ibovespa closes that agree between B3's JSON and CSV export. It makes each month's value eligible at the next UTC month boundary. The original 30-day window produced only an opening per market. A separate six-month follow-up produced eight closures under the same rule. [Ibovespa replay](fmz-round16-ibov.json) · [B3 statistics](https://sistemaswebb3-listados.b3.com.br/indexStatisticsPage/daily-evolution/IBOVESPA?language=pt-br)

## Remaining dependencies checked

- FMZ #4547 has checksum coverage for all 51 archived instruments across three 2022 months. The native simulator lacks the expected account and position payloads and clears the contract binding when the source changes symbols. Its original cross-sectional result remains pending. [Native host receipt](fmz-native-ghost-inputs-round16.json)
- FMZ #1389 and #1391 have distinct trading rules. Both terminate before reading data because the source names an undefined exchange constructor. The account adapter and contract-unit semantics still need evidence. [HTX binding controls](fmz-native-htx-binding-round16.json)
- FMZ #961, #985 and #4595 need matched inverse contracts. The paired January 2021 sample shows that the generic quarterly tape differs from the dated BTC and ETH contracts. [Dated contract cross-check](fmz-native-inverse-dated-crosswalk-round16.json)

The repository suite passed 340 tests and 89 subtests. The workbook validation checks new rows, 366 candidate statuses, formatting and the full result table range. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round16-coverage.json)
