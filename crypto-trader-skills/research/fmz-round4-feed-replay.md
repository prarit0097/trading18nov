# FMZ Pine historical feed and runtime replays

This pass reviewed 260 unresolved IDs from the [third follow-up coverage ledger](remaining-backtest-round3-coverage.json). It attempted 104 historical replays and verified **67 newly tested IDs and 402 result rows**. Fifty-nine strategies closed at least one lot and eight ran without closes. Each accepted strategy has six historical rows. Each of the two screening windows has a Binance USD-M BTCUSDT replay, an ETHUSDT replay, and a pooled row. Positive P&L and win counts are shown at three cost levels. The broker uses candle-level fills with 5.9 basis points per side in fees, a separate 3 basis points per side in modeled execution costs, and the common 10,000 USDT starting balance unless an archived capital override was previously verified. [Replay results](fmz-round4-feed-replay.json) · [Independent fixtures](fmz-round4-feed-fixtures.json)

- Resource retries kept the frozen Pine source and candle inputs from the earlier runs. The worker used a 160-second candidate limit, a 1,024 MB old-generation heap, and a fresh worker for each candidate. The report retains the unsuccessful 15-minute and 60-minute attempts. Successful 15-minute rows take precedence over 60-minute sensitivity rows. The historical-bar worker uses an 80-second limit, with a 55-second limit for the fixed benchmark batch.
- Historical mode resolves realtime flags against fully historical chart windows. A final historical-bar check uses the final chart bar. Sources with one chart calculation per bar retain cross-bar persistence from the archived declarations. Clock snapshots use each screening window's own closing timestamp, which can change a source's date-dependent signals. These rows carry the **window-end clock snapshot** label. [Pine execution model](https://www.tradingview.com/pine-script-docs/language/execution-model/) · [Pine time semantics](https://www.tradingview.com/pine-script-docs/concepts/time/)
- Strategies that used future-looking references were evaluated in a separately labeled **confirmation-timing variant**. It reads a completed higher-timeframe candle or the most recent completed lower-timeframe candle. Verified helpers that already read a preceding market candle retained the original offset and alignment. Heikin-Ashi references supply signals while historical fills use exchange candles. The OHLC fill-recalculation label identifies sources that may use completed-bar values during simulated fills. [Pine request semantics](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/) · [Pine synthetic chart data](https://www.tradingview.com/pine-script-docs/concepts/non-standard-charts-data/)
- The feed extension added 105-minute and 300-minute reference series from checksum-verified Binance archives. A four-day reference was also staged for the helper checks. The fixed BTC benchmark candidates preserve the archived Binance BTC perpetual benchmark on both the BTC and ETH fill charts. [Public Binance data](https://github.com/binance/binance-public-data)

The no-network Windows AppContainer denied access to an external connection and a file outside its scratch directory. The study records the pinned source and derived source hashes, exact market inputs, worker hashes, per-batch receipt hashes, and rejected candidates. Independent fixtures reconcile costs and sizes and exercise monthly alignment, lower-timeframe selection, distinct cross-symbol feeds, and per-window clock values. Archive code, local scratch, and runtime dependencies stay local.

The remaining dependencies include historical intrabar state, unsupported Pine features, unresolved exact benchmark symbols, and legacy session windows beyond the chart timeframe or expressed as a close time. The 1,440-minute UTC alias for strategy 4098 and the monthly-history case 5441 still exhausted their isolated worker bounds. [Prior daily alias alignment check](fmz-round3-utc-alias-check.json)

## Reproduce

Use the pinned FMZ ZIP, the prior round scratch results and public archive caches, the PineTS 0.13.1 runtime, and the no-network AppContainer from the prior research. Run the staging and finalization commands from the skill root. Run every generated batch and fixture worker inside the allowed scratch directory with its candidates, candles, and staged engine. Collect UTF-8 `out.jsonl`, its launcher exit receipt, and a successful isolation probe. The generated scratch directories are listed in the JSON manifest.

```powershell
python -m research.fmz_round4_feeds preflight prior-scratch work
python -m research.fmz_round4_feeds stage-runtime prior-scratch work
python -m research.fmz_round4_feeds stage-new prior-scratch work
python -m research.fmz_round4_feeds stage-addon prior-scratch work
python -m research.fmz_round4_feeds stage-benchmark prior-scratch work
python -m research.fmz_round4_feeds stage-fixtures prior-scratch work
python -m research.fmz_round4_feeds finalize prior-scratch work --output research/fmz-round4-feed-replay.json --fixture research/fmz-round4-feed-fixtures.json
```
