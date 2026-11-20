# FMZ Pine historical feeds and session replay

This pass reviewed 160 unresolved Pine feed, runtime, and session cases from the fourth follow-up ledger. It verified 44 additional strategies and 264 result rows. Thirty-four strategies closed at least one position, and ten ran without a close. The results record the pinned FMZ document hash and the adapted Pine code hash for every attempted replay, together with candle, worker, and receipt hashes. Each accepted strategy has a BTCUSDT result, an ETHUSDT result, and a pooled result for each of the two historical windows. [Coverage and replay results](fmz-round5-feeds.json)

- Both charts use public Binance USD-M perpetual candles on a 15-minute grid. The replay retains the previous candle histories and assembles the extra reference intervals from the same verified archives. The PineTS candle broker uses a common 10,000 USDT starting balance unless an archived constant is verified. The default order value is 1,000 USDT, with explicit source quantities preserved. The broker applies 5.9 basis points per side in trading fees. The report also applies 3 basis points per side in modeled execution costs to closed trades. [Binance public archives](https://github.com/binance/binance-public-data)
- References to incomplete higher-timeframe candles are delayed in the confirmation-timing variants. The same worker fixture verifies monthly offsets, Heikin-Ashi reference values, and the most recent completed lower-timeframe candle. Fixed BTC benchmark runs route the archived Binance BTC perpetual to both charts. Strategy 1821 retains its published setting with the reference-market filter disabled. The cross-symbol fixture distinguishes the benchmark from the ETH chart and from a separate spot series. [Pine reference timing](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)
- Legacy session migrations preserve the original weekday defaults or explicit day selectors. Session cases based on membership in a one-minute interval use the 15-minute UTC chart open in a labeled variant. The weekday fixture checks a session open and end at exact boundaries, then checks the same interval on a Saturday. The replay converts invalid `2400` session boundaries to Pine's midnight spelling where the source specifies that boundary. [Pine sessions](https://www.tradingview.com/pine-script-docs/concepts/sessions/) · [Pine v5 day default](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)
- The historical calculation path resolves realtime-only Pine flags and preserves verified constant settings. Results requiring OHLC fill recalculation carry that label. Sources still requiring a Bar Magnifier path, unavailable tick or session state, an unverified external series, or a source repair remain pending with the observed dependency or runtime error. [Pine broker and recalculation](https://www.tradingview.com/pine-script-docs/concepts/strategies/)

Each numeric fixture checks six result rows. In the standard three-candle fill fixture one unit enters at 1,000 and exits at 1,050 for 50 gross and 48.1755 after modeled costs per market. The no-network Windows AppContainer denied a network connection and a read outside the scratch directory. The published report contains result rows, source and artifact hashes, and fixture measurements.

## Reproduction

Use the previous round's Pine scratch with its pinned `fmz.zip`, Binance archive caches, extended input candles, and the isolated PineTS runtime. From the skill root, stage and run these batches in order.

```powershell
python -m research.fmz_round5_feeds stage prior-scratch round4-feeds work --prefix batch
python -m research.fmz_round5_feeds stage prior-scratch round4-feeds work --prefix sessions
python -m research.fmz_round5_feeds stage prior-scratch round4-feeds work --prefix repair
python -m research.fmz_round5_feeds stage prior-scratch round4-feeds work --prefix followup
```

Use the prior AppContainer launcher, Node bridge, runner, and isolation probe in `work`. Run every generated batch and fixture directory, including `session-check`. Keep its UTF-8 `out.jsonl` and corresponding launcher exit receipt.

```powershell
python -m research.fmz_round5_feeds finalize prior-scratch/fmz.zip work research/fmz-round5-feeds.json --prefixes batch sessions repair followup
```
