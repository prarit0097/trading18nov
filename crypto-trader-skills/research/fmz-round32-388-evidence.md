# FMZ #388 Goblin Town bracket and sizing evidence

The versionless Pine archive supplies repeated entry IDs and two
relative take-profit orders per side. The diagnostic restores v4,
uses the corresponding legacy names, removes two trailing commas
and supplies an integer history length in the disabled zero-lag
branch. It uses 744 Binance USD-M hourly candles per market over
January 2024, with daily candles aggregated from the same official
15-minute source. The archive names a 60-minute interval and omits
a saved market or execution window.
[Pinned strategy source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/Goblin-Town-60min-%E5%8F%AF%E7%94%A8%E7%89%88.md) · [FMZ strategy page](https://www.fmz.com/strategy/376304)

Whole-contract units remove two floating-point fragments from the
ETH diagnostic. One internal contract represents 0.001 base units
through the point-value multiplier. The strategy never reads
position quantity or submits explicit quantities. The normalized and
base-unit runs agree on signals and all economically meaningful native
trade details. The floating-point baseline recorded residual quantities
below the minimum lot as separate exits.
[Binance minimum order increments](https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition#lot_size)

The primary runtime executes two shared-ID entries at 100 and 200
against a bracket with a 10-tick target. It closes both at 110.
The distinct-ID control closes at 110 and 210. Both Piner 0.13.0
backends close at 110 and 210 with either ID arrangement. This isolates
the primary runtime's shared-basis behavior. TradingView documents
relative distances from the entry and a separate exit for each
corresponding entry sharing an ID.
[TradingView relative and absolute levels](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/#take-profit-and-stop-loss) · [TradingView multiple entries](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/#exits-for-multiple-entries)

The alternate runtime fails a same-open sizing control. Both entries
are submitted at the prior close and enter at 100. Changing only the
new bar's future close from 50 to 150 changes the second Piner size from
62.492 to 37.492. The native integer-lot control stays at 49.985 and
49.977 base units for the pair in both cases. The alternate historical
projection also executes 37 BTC and 39 ETH exits between exchange price
ticks. These execution defects leave catalogue status pending. The
tested pivots, fixtures and diagnostics support no performance row.

## Reproduce

Save the pinned source as `PyScratch/source-388.md`. Use the official
Round 30 January inputs and the same isolated Python and Node runtimes.
Keep the compiled package and raw outputs outside the repository.
[Round 30 January staging](fmz-round30-1070.md) · [Pinned Pine Compat runtime](fmz-round11-magnifier-priced.md) · [Pinned Piner distribution](fmz-round7-magnifier.md)

```powershell
python -m research.fmz_round30_1070_stage PublicInputs PyScratch
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round32_388_runner.py PyScratch/probe_388.py
Copy-Item research/fmz_round32_388_stacked.py PyScratch/388_stacked_fixture.py
Copy-Item research/fmz_round32_388_sibling_native.py PyScratch/388-sibling-native.py
PyScratch/sandbox.ps1 PyScratch probe_388.py '' 120
PyScratch/sandbox.ps1 PyScratch 388_stacked_fixture.py '' 120
Copy-Item PyScratch/source-388.md,PyScratch/1070-BTCUSDT.json,PyScratch/1070-ETHUSDT.json,PyScratch/388-probe.json,PyScratch/388-stacked-fixture.json NodeScratch
Copy-Item research/fmz_round32_388_stacked.mjs NodeScratch/388-stacked-fixture.mjs
Copy-Item research/fmz_round32_388_historical.mjs NodeScratch/388-piner-historical.mjs
Copy-Item research/fmz_round32_388_sibling.mjs NodeScratch/388-sibling-causality.mjs
NodeScratch/sandbox.ps1 NodeScratch 388-stacked-fixture.mjs '' 60
NodeScratch/sandbox.ps1 NodeScratch 388-piner-historical.mjs '' 60
NodeScratch/sandbox.ps1 NodeScratch 388-sibling-causality.mjs '' 60
Copy-Item NodeScratch/388-sibling-causality.json PyScratch
PyScratch/sandbox.ps1 PyScratch 388-sibling-native.py '' 60
python -m research.fmz_round32_388 PyScratch NodeScratch Evidence.json
```

[Verified bracket and sizing receipts](fmz-round32-388-evidence.json)
