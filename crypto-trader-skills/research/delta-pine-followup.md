# Legacy Pine follow-up on BTC and ETH

This pass reviews the remaining 1,322 Pine strategies from the [migration](delta-pine-migration-replay.md) and [compiler repair](delta-pine-repair.md) batches. The replay passed for 275 strategies. Of these, 227 recorded at least one closed lot and 48 had zero closed lots across both coins and windows. The original workbook's **Delta backtests** sheet adds 1,650 rows under **FMZ Pine follow-up**. **Test coverage** records the outcome of all 1,322 entries, including the 1,047 still pending.

## Source compatibility and candle intervals

- The input rewrite preserves literal values when legacy syntax repeats an identical default, uses a leading zero on an integer, declares a known positional or old-style type, or uses an integer-valued decimal bound for an integer input. Conflicting defaults and fractional integer bounds require separate evidence.
- An unshadowed global binding can be renamed when it collides with a Pine v5 reserved word or namespace. Property names, named arguments and built-in calls retain their own identifiers. The eager `iff` rewrite supports a narrow set of direct top-level assignments, evaluating both indicator branches on every candle. Previously verified prior-bar recursion and explicit direction rewrites still apply. [TradingView migration to v4](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-4/) · [TradingView migration to v5](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)
- Source repairs use 15-minute candles and retry at 30 minutes only if a modeled fill used a candle without traded volume. A strategy previously rejected at 15 and 30 minutes can be replayed on its archived interval if it can be reconstructed from the measured 5-minute data. Archived intervals are aligned to UTC, with only complete candles inside each window. The 1-day candidates require independence from daily timeframe metadata because the runner identifies intervals in minutes. The interval choice depends on recorded evidence and fill validity. The replay rejects any remaining fill on an untraded candle.
- Common pending dependencies include external data or chart scope, a missing active strategy declaration, tick or intrabar recalculation, and compiler errors. Each pending entry retains a reason in the workbook and machine-readable report.

## How to read the results

Both windows use the same public Delta India testnet candle digests as the previous batch. They cover 23 September–20 October 2026 and 21 October–3 November 2026, inclusive in IST. Each coin is replayed independently. Combined rows pool realized exits by timestamp. Gross P&L uses modeled fill prices. After-fee P&L deducts 5.9 basis points per side. The all-cost estimate also deducts 3 basis points per side for spread and slippage. Win rates use closed lots, including partial exits, and are blank when no lots close. Drawdown uses realized P&L from a $10,000 reference equity. Explicit source quantities and pyramiding may produce substantially different exposure from the $1,000 default.

Fourteen strategies had positive pooled P&L after all modeled costs in both windows. Four of those had at least 30 pooled closed lots in each window. Those counts describe the periods screened here. The two windows were used to screen the catalogue, so this comparison does not provide fresh out-of-sample qualification. The broker model excludes funding, dynamic margin, liquidation and queue execution.

## Reproduce

Use PineTS 0.13.1, the pinned FMZ source archive and both public Delta caches from the [previous replay](delta-pending-catalogue-replay.md). From the skill root, run:

```powershell
python -m research.delta_pine_followup prepare fmz.zip reference.json later.json work
```

For each interval listed in `work/batches.json`, run the same isolated `research/delta_pinets_worker.mjs` command used by the native replay with that folder's `candidates.json` and `candles.json`. Write its JSON lines to the folder's `out.jsonl`. Then prepare the 30-minute retry, run its worker if the directory exists, and finalize:

```powershell
python -m research.delta_pine_followup retry reference.json later.json work
python -m research.delta_pine_followup finalize work research/delta-pine-followup.json
```

A deterministic candle fixture compared the rewritten legacy strategy with a direct Pine v5 equivalent and independently calculated the entry, exit, fees and net P&L. The finished workbook was checked against the replay manifest for every added metric and updated coverage row.
