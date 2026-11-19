# Repairing legacy Pine recursion and compiler errors

This batch uses the pending coverage list from the [legacy Pine migration](delta-pine-migration-replay.md). It selects the 425 entries with an implicit recursive series finding or a PineTS compile/runtime finding. Other pending entries keep their existing coverage reasons. The source revisions, candle digests and strategy IDs match the earlier catalogue.

## Repair rules

- The recursive-series repair accepts a single top-level assignment. Every self-reference must read a literal positive bar offset. Parenthesized expressions can span multiple lines. A small type check must prove a numeric or Boolean result from the source. The repair declares the proven type with an initial `na` and assigns the same expression using `:=`. This preserves the original warm-up branches and thresholds. Current-bar, future, dynamic and forward references remain pending.
- Legacy literal directions are passed to the corresponding Pine directional constant. Built-in call names use the Pine v5 namespace. A local variable with the same name retains its original reads.
- A standalone legacy `strategy.exit` call with no executable order parameters can compile as a no-op. The repair retains that legacy behavior. Cases with incomplete trailing orders or callable argument expressions remain pending. A missing active strategy declaration, a write to a broker-owned wallet field, or an ambiguous input default requires separate evidence. [Pine v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)

An independent candle fixture checked integer state persistence across neutral bars, a floating-point recurrence, the unchanged behavior of a legacy no-op exit, and the resulting entry/exit and commissions. Every published repair can be regenerated from its pinned source and compared with the recorded digest.

## Replay

The same 23 September–20 October and 21 October–3 November 2026 IST Delta testnet windows were used on BTCUSD and ETHUSD. The broker uses 15-minute aggregate candles. Untraded-candle fills trigger a 30-minute retry, following the [PineTS replay model](delta-pending-catalogue-replay.md). The default order size is $1,000 of notional at the signal. Explicit source sizes remain in effect. Fee-only P&L uses 5.9 basis points each side. All-cost P&L also deducts 3 basis points each side for modeled execution costs. Drawdown uses realized P&L with a $10,000 reference. Win rates use closed lots.

In **Delta backtests**, filter **Group** to **FMZ repaired Pine**. The **Repair applied** field describes each result. **Test coverage** includes the unresolved reason for each rejected repair or replay.

## Reproduce

Use the pinned FMZ archive, public Delta candles, TA-Lib and PineTS dependencies from the earlier studies. Run `python -m research.delta_pine_repair prepare fmz.zip reference.json later.json work` from the skill root. Run the same PineTS worker and `prepare-retry` commands as the prior migration. Export the results with `python -m research.delta_pine_repair finalize work research/delta-pine-repair.json --retry work/retry`.
