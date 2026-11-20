# FMZ Pine compatibility retries

This continuation uses the [remaining coverage checkpoint](remaining-backtest-coverage.json)
and the same public Binance USD-M BTCUSDT and ETHUSDT perpetual windows as the
previous round. The [strict replay](fmz-pine-remaining.json) and
[isolated literal replay](fmz-pine-remaining-literals.json) retain the catalogue
ID, pinned FMZ document digest, migrated-source digest and per-market outcomes.

The two passes accepted 210 of 370 scoped strategies and produced 1,260
metric rows. Of those strategies, 194 closed at least one lot and 16 closed
zero lots. The isolated run contributed 21 of the 210 accepted IDs. Eleven
strategies had positive pooled P&L after modeled costs in both screening
windows. Each had fewer than 30 pooled closed lots in at least one window.

Several FMZ archives declare an indicator or study and also include active Pine
order calls. FMZ supports an optional declaration. For a single declaration that
uses the chart interval, the adaptation supplies PineTS with the equivalent
strategy declaration and preserves the active conditions, order parameters and
source-defined quantities. An empty indicator timeframe uses the chart
interval. Explicit alternate timeframes and unknown declaration settings go
through separate verification. [FMZ Pine documentation](https://www.fmz.com/doc/9293) ·
[TradingView declarations](https://www.tradingview.com/pine-script-docs/language/declaration-statements/)

The compatibility pass also uses typed inputs when the archived arguments prove
the type, removes branch separators from flat switch blocks, and fixes
indentation only for complete local blocks that contain order calls under a
known guard. The strategies keep their archived input defaults. Historical
bar-close evaluation preserves the documented historical behavior of a source
that enables the realtime tick flag.
[TradingView Pine v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/) ·
[TradingView execution model](https://www.tradingview.com/pine-script-docs/v5/language/execution-model/)

PineTS 0.13.1 evaluates both windows on 15-minute bars. The market fixture retained
the 1,000 USDT default notional, Binance contract quantity rounding, the 5.9 basis
point fee and the 3 basis point execution allowance per side. The standard
worker reconciles price, quantities, fill volume, fees and reported P&L before
accepting each result. Its resource bound is longer than the previous pass.
The first strict run allowed 35 seconds per strategy. Revised or timed-out
sources had a 55-second run, and earlier results were reused only for identical
migrated-source and candle digests. The literal run used the 35-second bound.
The literal pass verified that a Windows AppContainer denied networking and
access to an outside file before admitting strings with escaped or structured
text. The executable source checks remain in force.

An independent chart fixture compared the rewritten strategy with a manually
declared Pine v5 equivalent. All six result rows matched, including three closed
lots per market with independently calculated rounded quantities, fill prices
and fees.

The 160 remaining local entries include sources requiring intrabar or
wallet semantics, ambiguous source declarations and recursive state, and
compiler or runtime limits. The manifests record the specific stage and
reason for each decision.

## Reproduce

Use the pinned FMZ ZIP and the [previous Binance candle archives](delta-pine-liquid-replay.md).
From the skill root, stage the strict pass, run the generated worker and collect
compiler details.

```powershell
python -m research.fmz_pine_remaining prepare fmz.zip binance-cache work
$pineTsEngine = Resolve-Path node_modules/pinets/dist/pinets.min.es.js
node work/worker.mjs work/candidates.json work/candles.json $pineTsEngine 4 > work/out.jsonl
node research/delta_pine_compatibility_preflight.mjs work/candidates.json $pineTsEngine > work/diagnostics.jsonl
python -m research.fmz_pine_remaining finalize work research/fmz-pine-remaining.json --diagnostics work/diagnostics.jsonl
```

Prepare the isolated tranche with `--isolated-literals`. Run the generated
worker in the [verified no-network AppContainer](remaining-backtests.md) before
finalizing with its isolation receipt and local JSONL.
