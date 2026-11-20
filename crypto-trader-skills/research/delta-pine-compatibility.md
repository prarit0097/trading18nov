# FMZ Pine source compatibility replay

This pass revisited 578 FMZ Pine catalogue entries with source compatibility or
runtime findings. It used the pinned FMZ archive and the existing public Delta
India testnet candle windows. The JSON manifest retains the previous outcome,
final coverage reason and each replay interval for all 578 catalogue IDs.

157 strategies produced accepted replays. Of those, 139 closed at least one
lot and 18 closed zero lots across both markets and windows. The other 421
remain pending. The [manifest](delta-pine-compatibility.json) includes 942 metric
rows and records the outcome of each catalogue ID.

Sixteen strategies had positive pooled P&L after all modeled costs in both
screening windows. Strategy 4623 was the only one of those with at least 30
pooled closed lots in each window. These counts describe the two screening
windows.

## Source evidence

- FMZ accepts a Pine strategy with active orders and no declaration. For those
  scripts, PineTS receives a title-only broker declaration. Commented declarations
  remain comments. The replay uses the campaign's standard broker settings and
  preserves explicit quantities in the active order calls. The FMZ documentation
  also identifies Pine v5 as the default for unversioned source.
  [FMZ Pine documentation](https://www.fmz.com/doc/9293)
- Classic RSI calls migrate when the length is a provably positive integer literal
  or a simple immutable integer default. The previous token check treated
  multi-digit literals as multiple tokens and could reject even a length of 14.
  Calls whose types leave the removed overload unresolved remain pending.
  Documented built-in namespace changes preserve how their source references are used.
  [TradingView Pine v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)
- Legacy `time()` calls on the chart interval get the weekday suffix when their
  session omits days. Explicit day sets and 24-hour shorthand are preserved.
  The replay uses TradingView legacy session rules on Delta's UTC calendar.
  Other timeframes, computed sessions and close-time filters require separate
  verification. [TradingView v4 sessions](https://www.tradingview.com/pine-script-docs/v4/essential/sessions-and-time-functions/)
- A fixed-default repair retains the integer value and type. Lower and upper
  fractional bounds round inward to the same allowed integers. A positive
  fractional step can be omitted because the default replay never changes
  values through the input widget. Conflicting defaults, invalid bounds and
  defaults outside their original bounds remain pending.
  [TradingView Pine inputs](https://www.tradingview.com/pine-script-docs/concepts/inputs/)

Compilation, market-data scope and broker checks all gate acceptance. Compiler
preflight calls PineTS' parser before configuring the broker to expose errors
that otherwise appear as a generic property-schema error. Remaining cases
include archived broker-wallet assignments, ambiguous recursive state, unsupported
source syntax, external dependencies and strategies that still fill at an
untraded price candle after the 30-minute retry.

## Replay and verification

PineTS 0.13.1 evaluated BTCUSD and ETHUSD separately in the existing reference
and later candle windows, 23 September–20 October and 21 October–3 November
2026 inclusive in IST. The replay used 15-minute candles, with a 30-minute
retry for strategies whose modeled fills used an untraded candle. The worker
validated prices, closing quantities, fee reconciliation and modeled fill
volume. The default cash order is $1,000, the fee is 5.9 basis points per
side, and the execution allowance is another 3 basis points per side.
Drawdown is calculated from realized P&L against $10,000.

A Friday-to-Monday fixture exercised the title-only adapter, integer RSI,
session days and fixed-default input normalization together. All six summary
rows matched a direct Pine v5 equivalent. The six weekday closed lots per
market were independently reconciled on fill price, quantity and fees.
The manifest was checked against the workbook's starting coverage reasons and
the pinned archive for every accepted row. The two market rows reconcile with
the combined market row for counts, costs and P&L in both windows.

## Reproduce

Use the pinned FMZ archive, PineTS 0.13.1, TA-Lib and the candle caches from
the [earlier replay](delta-pending-catalogue-replay.md). From the skill root,
prepare the candidate set and run the isolated replay worker.

```powershell
python -m research.delta_pine_compatibility prepare fmz.zip reference.json later.json work
$pineTsEngine = Resolve-Path node_modules/pinets/dist/pinets.min.es.js
node research/delta_pinets_worker.mjs work/15/candidates.json work/15/candles.json $pineTsEngine > work/15/out.jsonl
python -m research.delta_pine_compatibility retry reference.json later.json work
```

Run the same worker on `work/30` when the retry stage produces that directory.
The optional preflight records exact compiler details from the screened 15-minute
candidate set before the final join.

```powershell
node research/delta_pine_compatibility_preflight.mjs work/15/candidates.json $pineTsEngine > work/compiler.jsonl
python -m research.delta_pine_compatibility finalize work research/delta-pine-compatibility.json --compiler-diagnostics work/compiler.jsonl
```
