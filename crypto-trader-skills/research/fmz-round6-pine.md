# Round-six FMZ Pine audit and offline replay

This pass starts from the pending entries at commit `91ad53db55d0a62ced88ce239d3200fc2029980a`. The source audit covers 252 Pine, feed and intrabar entries plus 23 older chart or implicit-declaration entries. The report records each archived document hash, code block count, and evidence of active orders. Strategies with unverified execution or inputs retain a concrete pending reason. [Coverage and replay results](fmz-round6-pine.json)

The existing fixed Binance BTCUSDT and ETHUSDT USD-M 15-minute charts provide both historical windows. The engine is the pinned PineTS 0.13.1 artifact. It uses 10,000 USDT for modeled equity, 1,000 USDT for default order value and 5.9 bp per side in fees. Net P&L also deducts 3 bp per side in modeled execution costs. Where the archive proves an unconditional positive capital setting, the replay preserves that capital. Funding is outside this broker model. Every accepted strategy contributes BTC, ETH and pooled rows for each of two windows. [Input archive methodology](fmz-round5-feeds.md) · [PineTS releases](https://github.com/LuxAlgo/PineTS/releases)

The source-specific repairs retain typed inputs, actual archived default values, original stop-price expressions, legacy built-in namespaces, and prior-bar offsets. Declaration variants use the actual archived order commands and an offline broker declaration. The report labels time-confirmation, window-end clock, OHLC-fill recalculation, and Heikin-Ashi variants separately.

Where every audited helper call uses the current chart, its symbol binding is made explicit. The historical no-repaint wrapper keeps its one-chart-bar output delay. Candidate files retain only the reference timeframes established by literal requests when their entire request set is statically known. Dynamic timeframes keep the available pinned reference set. The separate cross-symbol fixture compares an independent BTC spot feed, BTC perpetual and the ETH chart through the production provider. [TradingView external timeframe semantics](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)

Each Windows AppContainer denied network and private-file access. The same worker checked a deterministic pricing and execution fixture before reported results were admitted. The Pine worker's per-source wall-clock limit is 135 seconds and its old-generation heap limit is 1,152 MB. Fork and exit receipts, market inputs, candidate source, worker and output digests appear in the machine-readable report.

## Reproduction

Stage the previous round's isolated Pine scratch, the pinned archive and verified 15-minute chart and reference candles. Run the generated `fixture-pine`, `fixture-cross` when present, and all generated `pine-*` directories through the prior AppContainer launcher. Retain each launcher exit receipt and the corresponding `out.jsonl`.

```powershell
python -m research.fmz_round6_pine stage FMZ_ZIP Round5Feeds Main
python -m research.fmz_round6_pine stage FMZ_ZIP Round5Feeds Extra --lane extra
python -m research.fmz_round6_pine stage FMZ_ZIP Round5Feeds Diagnostic --lane diagnostic --diagnostic-inputs Main Extra PriorSymbolRecovery
python -m research.fmz_round6_pine merge FMZ_ZIP research/fmz-round6-pine.json Main Extra Diagnostic
```

`PriorSymbolRecovery` is the staged history from the round-three symbol fixture, with its separately archived BTC spot series. `--only` selects a bounded retry of an existing lane without changing its data or execution model.
