# FMZ Pine data-dependency replays

All 46 Pine strategies that previously produced a modeled fill on an untraded
Delta candle closed at least one lot when replayed at 15 minutes on public
Binance USD-M BTCUSDT and ETHUSDT candles. The separate 30-minute run returned
closed lots for the same 46 IDs. Each interval produces 276 rows covering
BTC, ETH and the combined portfolio in the two screening windows. The coverage
ledger uses the 15-minute results. [15-minute results](fmz-round3-liquid-15m.json) ·
[30-minute results](fmz-round3-liquid-30m.json)

Extended Binance references recovered 22 of the 23 Pine strategies that had
explicitly failed for missing timeframe data. Sixteen closed lots and six
closed none, for 132 rows. A retry recovered ID 4029. ID 5441 exceeded the
115-second bound. Ten recovered IDs preserve the earlier confirmed-timing
variant that delays unsafe future-looking requests until the reference candle
confirms. The row groups identify those variants.
[Extended timeframe results](fmz-round3-timeframes.json)

The reference feed pass used the archived Binance BTC benchmark on both BTC
and ETH fill charts. The two explicit TradingView `BINANCE:BTCUSDT` sources
were staged with Binance spot prices and still failed compilation. Verified FMZ
perpetual aliases stayed on Binance USD-M.
The 53-ID scope came from the previous ledger's unavailable-symbol reason.
Eleven strategies produced 66 rows. Ten closed lots and one closed none.
Four of the 11 completed in a six-source compatibility retry. Remaining entries
include missing exact instrument histories, unresolved request routing,
compiler failures and two runtime timeouts. The specified Glassnode USDT
supply and IntoTheBlock BTC hashrate feeds remain open dependencies.
[Reference feed results](fmz-round3-symbols.json) ·
[FMZ instrument notation](https://www.fmz.com/syntax-guide/conventions/symbol) ·
[TradingView Binance BTCUSDT listing](https://www.tradingview.com/symbols/BTCUSDT/?exchange=BINANCE)

Across the three canonical runs, 79 strategies produced 474 rows. Seventy-two
closed at least one lot. None of the 79 posted positive combined net P&L in
both windows. In the 30-minute sensitivity run, ID 3506 posted 34.70 USDT
across 53 closed lots in the reference window and 61.33 USDT across 30 closed
lots in the later window. Its 15-minute results failed the same screen.

The BTCUSDT and ETHUSDT order-fill candles retain the standard 5.9 basis point
fee and 3 basis point execution allowance per side. Archived Pine order sizes
take precedence over the fixture's default 1,000 USDT cash order. Realized
drawdown uses the broker's starting equity, normally 10,000 USDT. Remaining
open lots are counted separately. The replay models historical OHLC fills.

The extended-reference data use checksum-verified 1-minute archives from
June 2026 and public daily candles from January 2020. Every overlapping UTC
day through 3 November 2026 reconciles on OHLC and volume. Subdaily reference
bars align to UTC day starts. The last nondividing bucket in a day ends at
midnight. Multi-day groups start from the first day of the UTC year, weekly
bars start on Monday and monthly bars use the UTC calendar. A terminal partial
reference candle retains its natural close and contains only prices observed
by the window cutoff. This lets the engine use the preceding confirmed
reference without seeing future prices. These are the recorded alignment
conventions for the compatibility replay.
[Binance public data](https://github.com/binance/binance-public-data) ·
[TradingView historical request semantics](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)

Two independent synthetic fixtures run through the same respective production
workers in a no-network Windows AppContainer. They verify month confirmation,
monthly history offsets, Heikin-Ashi history and last closed 2-minute candle
selection. The cross-symbol fixture also distinguishes BTC perpetual and spot
reference prices from the ETH fill-chart price. Each row reconciles its modeled
lot count and independently calculated costs and P&L.
[Extended feed fixture](fmz-round3-feed-fixture.json) ·
[Reference feed fixture](fmz-round3-symbol-feed-fixture.json)

## Reproduce

Use the pinned FMZ ZIP and PineTS 0.13.1 with the previously verified no-network
AppContainer runner. Keep private files outside the allowed scratch root. In
the commands below `binance-cache` contains the public 5-minute archives and
`round2-cache` is the public Binance spot and futures 1-minute cache from the
previous research. Missing extended UTC day or minute data are fetched from
Binance's public endpoints when preparing the candidates.

```powershell
python -m research.fmz_round3_liquid_feeds prepare fmz.zip binance-cache work/liquid15 --minutes 15
python -m research.fmz_round3_liquid_feeds prepare fmz.zip binance-cache work/liquid30 --minutes 30
python -m research.fmz_round3_timeframe_feeds prepare fmz.zip binance-cache round2-cache work/cache work/timeframes
python -m research.fmz_round3_symbol_feeds prepare fmz.zip round2-cache work/cache work/timeframes work/symbols
python -m research.fmz_round3_feed_fixture prepare work/fixture
python -m research.fmz_round3_feed_fixture prepare work/cross-fixture --cross
```

Save a successful isolation probe as `isolation-probe.json` in each batch
directory. Run each generated `worker.mjs` in the same scratch AppContainer,
passing its `candidates.json`, `candles.json`, the local PineTS module staged
as `work/engine.mjs`, and concurrency `3`. Capture output as UTF-8 `out.jsonl`.
After the initial timeframe run, generate its retry with
`python -m research.fmz_round3_timeframe_feeds prepare-retry work/timeframes work/timeframes-retry`
and run the retry in the same AppContainer. Stage the cross-symbol compatibility
retry with `python -m research.fmz_round3_symbol_feeds prepare-recovery fmz.zip work/symbols work/symbols-recovery`
and run it the same way.

```powershell
python -m research.fmz_round3_feed_fixture verify work/fixture research/fmz-round3-feed-fixture.json
python -m research.fmz_round3_feed_fixture verify work/cross-fixture research/fmz-round3-symbol-feed-fixture.json
python -m research.fmz_round3_liquid_feeds finalize work/liquid15 research/fmz-round3-liquid-15m.json
python -m research.fmz_round3_liquid_feeds finalize work/liquid30 research/fmz-round3-liquid-30m.json
python -m research.fmz_round3_timeframe_feeds finalize work/timeframes research/fmz-round3-timeframes.json research/fmz-round3-feed-fixture.json --retry work/timeframes-retry
python -m research.fmz_round3_symbol_feeds finalize work/symbols research/fmz-round3-symbols.json research/fmz-round3-symbol-feed-fixture.json --retry work/symbols-recovery
```
