# Legacy Pine migration and BTC/ETH replay

This batch starts with all 2,156 FMZ catalogue entries previously marked as Pine 2–4 or unversioned. Only pinned source documents are used. The migrated source has a content digest, the original Pine version and a record of the transformations applied. Original catalogue IDs are retained.

## Migration rules

- For explicit Pine v2, v3 and v4 sources, the adapter targets Pine v5 and rewrites known built-ins to their Pine v5 namespaces. It converts supported input declarations to the corresponding typed input while preserving the defaults and constraints. It prefixes legacy color and plot-style constants where their context is clear.
- The adapter resolves legacy RSI lookbacks only when the second argument is a positive literal or a static integer input. The older overloaded RSI formula requires a separate adapter.
- A follow-up rewrites `iff` only when both branches are plain reads or approved pure calculations. It rewrites `offset(series, n)` only for a named series and a literal nonnegative history offset. Stateful eager branches require a verified rewrite.
- A compiler-error follow-up resolves a known built-in function call when a legacy variable shares its name. The variable reads stay unchanged. Names declared as user functions are outside this recovery rule.
- Unversioned source, implicit recursive state, external feeds, calendar differences, intrabar settings and unsupported syntax remain pending. The replay can also reject a migration for a compiler or runtime failure, a warning, an untraded fill or an unreconciled trade ledger.

These are source-preserving automated migrations for a supported subset. The verified checks include independent candle-timing and fee fixtures for typed inputs, moving averages, read-only `iff` and `offset`. The runtime uses PineTS 0.13.1. Historical results can differ from archived TradingView runs due to runtime, candle frequency, data and execution settings. [TradingView v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/) · [TradingView v4 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-4/)

## Replay and workbook

Both BTCUSD and ETHUSD run on the prior Delta testnet windows of 23 September–20 October and 21 October–3 November 2026 IST. The first run uses 15-minute candles. Any candidate with a modeled fill on a candle with zero traded volume is retried at 30 minutes. This decision uses fill validity alone. The broker and costs match the [native PineTS replay](delta-pending-catalogue-replay.md). The default broker order size is $1,000 cash at the signal. The filled notional can vary with gaps. Explicit source quantities and pyramiding are retained. Fees are 5.9 basis points each side. Modeled spread and slippage add 3 basis points each side after the fact. The win-rate denominator is closed lots, including any completed partial lot. P&L and drawdown use realized fills. The initial drawdown reference is $10,000.

The workbook's **Delta backtests** tab includes the **FMZ migrated Pine** group. Use the **Replay interval** and **Original Pine version** columns to compare results. **Test coverage** records a migration or replay reason for every source in the batch.

## Reproduction

Use the PineTS installation, pinned FMZ ZIP and public candles from the preceding batches. From `crypto-trader-skills`, use `python -m research.delta_pinets_migration prepare fmz.zip reference.json later.json work`. Use the same PineTS worker and `prepare-retry` commands as the native replay. Finalize using `python -m research.delta_pinets_migration finalize work output.json --retry work/retry`. Prepare and run the read-only follow-up in a second directory with `--expand-read-only`. Finalize the second directory and apply `python -m research.delta_pinets_migration merge-read-only output.json follow-up.json`. Prepare the last follow-up in a third directory with `--recover-from output.json`, then replay, finalize and apply `merge-recovered output.json recovered.json`.
