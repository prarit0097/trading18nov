# Fifth FMZ Pine compiler replay

The compiler pass reviews 92 unresolved FMZ catalogue IDs at commit `8fc965fe59c1cf0957c1abf09b4277ca9b2b1613`. It measured 37 strategies in 222 rows. Thirty-two recorded at least one close and five recorded zero closes. The two Binance USD-M perpetual windows and PineTS 0.13.1 engine come from the fourth compiler pass. The replay receipt includes each ID’s earlier disposition, pinned document digest, migration digest for executable candidates, and new status. [Coverage and results](fmz-round5-compile.json) · [Fourth coverage audit](remaining-backtest-round4-coverage.json)

- Seven capital variants interpret the archived, unconditional 50,000 USDT literal as starting broker equity and the drawdown reference. The existing capital adapter requires the override to precede executable capital and order expressions.
- Four named-default variants use the explicitly named literal where an archived widget supplies conflicting positional and named defaults. Identical duplicate boolean fields are normalized to the same archived value.
- Two display-free variants retain the order code and omit terminal chart-table calculations. The chart functions in nine other sources keep their calls, with the conflicting variable binding renamed.
- The RSI Breakout VWAP variant binds the crossover series before taking its archived 28-bar offset. Its source default was verified before making the offset a literal.
- The remaining repairs include explicit prior-bar state, a verified integer RSI argument, the legacy two-series RSI formula, an explicit expression result, and combined-indicator declarations whose active orders use both sets of calculations. ID 2169 uses the derived fixed lookbacks for RSI as a labeled variant. Pine v4 overload selection depends on the argument type. [TradingView Pine v5 migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)

The broker reconciles closed and still-open lots against the archived candles. Each measured ID contributes BTCUSDT, ETHUSDT and pooled rows for both windows. Modeled fees are 5.9 basis points per side. Net P&L additionally deducts 3 basis points per side in modeled execution costs. Drawdown uses realized fills against the configured equity reference. Source settings that require the historical bar-close variant stay labeled in the row repairs.

The receipt combines the completed batch with the targeted trial for ID 712. The accepted candidate text was checked byte for byte against the final manifest. A later whole-batch check hit the per-source resource limit for IDs 385, 462 and 907. Their completed runs used the same migrated sources, worker, candle file and engine.

The offline Windows AppContainer denied an outbound network connection and a read outside the replay stage. The deterministic fixture compared six rows with an independent control. Per market and window, two units entered at 104 and exited at 106. Gross P&L was 4 USDT, fee-adjusted P&L was 3.7522 USDT, and all-cost net P&L was 3.6262 USDT. [Fixture receipt](fmz-round5-compile-fixture.json)

Pending sources retain their compiler or data dependency. Examples include an undefined `n`, insufficient trailing-exit arguments, competing order directions sharing an active ID, and strategies that exceeded the bounded runtime. The FMZ manual requires priced exit arguments for `strategy.exit` and uses `strategy.close` or `strategy.close_all` for market exits. [FMZ Pine manual](https://www.fmz.com/doc/9293)

## Reproduce

From the repository root, stage the pinned FMZ ZIP, the round-four compiler retry work directory and its published report.

```powershell
python -m research.fmz_round5_compile prepare ARCHIVE research/remaining-backtest-round4-coverage.json PRIOR_WORK research/fmz-round4-compile-retry.json WORK
python -m research.fmz_round5_compile fixture WORK
```

Use the same isolated Node runner, PineTS engine and AppContainer probe as round four. Capture `fixture-out.jsonl`, `diagnostics.jsonl`, `out.jsonl` and `isolation-probe.json` in the stage directory. Finalization verifies the engine and migration hashes, checks the fixture and reconciles the published rows. [Round-four runner details](fmz-round4-compile.md)

```powershell
python -m research.fmz_round5_compile finalize WORK research/fmz-round5-compile.json research/fmz-round5-compile-fixture.json
```
