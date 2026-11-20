# Remaining strategy backtests · Round 7

Round 7 started from the 504 pending catalogue IDs in the verified Round 6 workbook. The original workbook's Delta backtests tab records win rate, gross P&L, P&L after fees, P&L after all costs and drawdown. The Test coverage tab records a source-linked status and reason for every catalogue ID.

This round verified 24 strategies across 131 added result rows. Nineteen strategies produced closed lots and five completed without closes. The original 785-ID backlog is now at 480 pending, with 305 IDs resolved across the last two rounds. The catalogue has 5,459 tested entries out of 6,184.

## Verified historical work

| Research lane | Additional IDs tested | Result rows |
| --- | ---: | ---: |
| FMZ Python native and source-based time-frame variants | 7 | 42 |
| FMZ Pine Bar Magnifier | 5 | 30 |
| FMZ Pine sessions, alternate engine, legacy migration and panel recovery | 8 | 48 |
| OctoBot grid and staggered order ladders | 2 | 8 |
| GMX dated share receipt scenarios | 2 | 3 |

- FMZ native runners used pinned public source, archived settings, checkable simulated fills and independent FIFO reconciliation. Some source-faithful variants sample faster decision loops at a documented cadence. [Native methods](fmz-native-round7.md)
- The Bar Magnifier tests used true lower-timeframe data over separate BTCUSDT and ETHUSDT windows. Both engine backends agreed, with no fallback to the chart's synthetic path. A separate audit reconstructed the original ten-second data for #5540 from public trade records. This strategy still needs verified account-currency conversion during sizing. [Bar Magnifier methods](fmz-round7-magnifier.md) · [Follow-up feed checks](fmz-round7-magnifier-followup.md)
- Pine sessions and legacy migrations retain the entry and order conditions checked against their pinned source. The alternate engine results identify the original and replay candle intervals. For #2999, an independent 14/28 SMA check confirmed all 328 closes at the modeled next open. The legacy safeguards reject code that compiles but silently changes strategy behavior. [Session evidence](fmz-round7-pine-sessions.json) · [Legacy evidence](fmz-round7-pine-legacy.json) · [MA panel evidence](fmz-round7-pine-panel.json)
- OctoBot used the archived mirror distance of spread less increment. The variants use a static grid, 20 or 25 levels per side, a 50/50 initial inventory, 90% of that inventory allocated to orders and one-second mirror placement delay. Captured Binance spot trade-through prices and available print quantity qualify fills. Four closed cycles were independently recalculated, and unattached inventory is reported separately. The fee is 10 bps and the execution buffer is 3 bps per side. [OctoBot archive](https://github.com/Drakkar-Software/OctoBot-Tentacles/tree/f0ebe0c14db0928e50c2e39ea68e2ff9f427f765/Trading/Mode) · [Ledger evidence](nonpine-round7-ladders.json)
- GMX used public Arbitrum receipt samples from October 1 and November 1. Observed share mints and burns bound the size of each matched lot. Deposits and redemptions are valued by the transaction's USDC oracle, and protocol fee logs and net keeper payments supply costs. Request gas and keeper fees use preceding Chainlink ETH/USD updates. Fees and gas on shared receipts are allocated in proportion to the matched shares. The report covers BTC-linked pools and lists cash flows from selected historical lots, with realized drawdown against the workbook's $10,000 reference. The sampled ETH receipts yield no eligible matched closed lot. [Liquidity rules](https://docs.gmx.io/docs/providing-liquidity/) · [Fee rules](https://docs.gmx.io/docs/api/contracts/fees/) · [Receipt evidence](nonpine-round7-gmx.json)

## Verification

Independent workbook verification matched all 131 appended rows and all 504 audited catalogue entries against the source reports. It also checked preservation of the existing result rows and the resized table range. The repository suite passed 327 tests and 89 subtests.

## Remaining work

The machine-readable audit counts tested IDs, exclusions, and open IDs against the exact Round 6 base. The per-ID records show whether a row has new runtime evidence, a specific remaining input or previously documented limits. A verified run without a closed trade has a blank win-rate cell. Known blockers include author-specific order settings, historical external feeds, unsupported broker behavior, missing executable quotes and protocol-specific settlement history. [Per-strategy audit](remaining-backtest-round7-coverage.json)

Delta Demo remains paused during the historical research.
