# FMZ market-order replays on BTC and ETH

This adds 188 FMZ catalogue entries to the existing Delta historical workbook. The source scan evaluated 5,097 catalogue documents with a BTC or ETH USD, USDT or USDC configuration. The replay recorded closed trades for 180 entries and zero closed trades for eight. **Test coverage** records the reason for each pending source. Eight zero-trade entries have blank win rates.

The adapter reads the pinned FMZ source archive and interprets a subset of Pine expressions, including default inputs, historical offsets, moving averages, crossovers and direct market entry or close commands. It uses no TradingView runtime. An opposite entry reverses at the next eligible opening price. One position per coin is allowed. The simulator uses archived entry and exit conditions, 5-minute Delta testnet BTCUSD and ETHUSD candles, and its own TA-Lib indicator initialization. Source intervals are recorded for comparison. Stateful scripts, external series, bracket orders, conflicting entries and unsupported expression or broker behavior remain pending.

The two IST windows run 23 Sep–20 Oct 2026 and 21 Oct–3 Nov 2026. The two windows use the same $1,000 entry notional, $10,000 initial equity, 5.9 bp per side trade fee and 3 bp per side spread/slippage assumptions as the [first replay](delta-strategy-replay.md). Drawdown uses realized exits. An open position at the period boundary is counted as unsettled and excluded from closed-trade P&L. A signal can fill at the next scheduled open when there is a traded candle. An unfilled signal is not carried to a later candle. Indicator state starts again after gaps in the candle sequence.

## Reproduction

Use the same TA-Lib and public Delta caches as in the first replay. Download the [pinned FMZ ZIP](https://codeload.github.com/fmzquant/strategies/zip/7853bb2bf262c4567ac238d3552d97f0e50cb801). From the `crypto-trader-skills` directory, run:

```powershell
python -m research.delta_fmz_replay fmz.zip reference.json later.json research/delta-fmz-replay.json
```

The JSON records source links, document hashes, candle digests, outcome totals and coverage reasons. The workbook includes separate BTC, ETH and pooled rows for each window.
