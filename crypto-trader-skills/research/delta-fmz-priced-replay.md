# FMZ stop and limit order replay

This batch evaluates previously pending FMZ scripts with a BTC or ETH quote configuration and an explicit stop or limit price, or a protective tick-distance order. The adapter reuses the pinned FMZ source archive and the two public 5-minute Delta testnet candle caches from the [market-order replay](delta-fmz-replay.md). Windows are 23 Sep–20 Oct and 21 Oct–3 Nov 2026, inclusive in IST. The workbook records the source interval for each script and uses 5-minute candles throughout.

## Fill and cost assumptions

- Signals evaluate at the candle close. Orders first become eligible on the following candle. Unfilled price orders rest until fill, replacement, cancellation or a gap in the available series.
- Existing orders that are marketable at the open use the open. An adverse stop gap therefore worsens a fill. A resting limit requires price to trade through the level. Touching the limit alone gives no fill.
- When an existing position's stop and target are both crossed intrabar and neither was eligible at the open, the stop wins. After an intrabar entry, an adverse stop may trigger on the entry candle; a target gets no credit on that candle. Bars without traded volume cannot execute orders.
- Each trade enters at $1,000 fixed notional. After-fee results deduct 5.9 bp each side. After-all-cost results also deduct 3 bp each side for modeled execution costs. The model applies the same rate to market and priced fills. Drawdown uses realized exits and $10,000 starting equity. Fees, spread and slippage are modeled estimates. Funding, liquidation, queue priority and trade-by-trade sequencing require additional data.
- An open position at a true candle-series gap or at the end of a window counts as unsettled. Its unrealized P&L is outside the summary. The model resets its order and position state across gaps. Relative protective order distances use the Delta testnet price ticks of $0.10 for BTCUSD and $0.05 for ETHUSD. Archived Pine scripts can use a different source exchange tick.

The evaluator covers full-position brackets, supported entry and close expressions, and basic cancellation. Source price thresholds retain their computed precision. Exchange tick rounding and size validation are outside this model. Scripts with unsupported state, multistage stop-limit orders, partial exits, outside feeds or competing intrabar orders remain pending with the reason recorded. These source-linked ports are historical research using a candle fill model. Positions in every window begin flat.

## Reproduction

Use TA-Lib 0.6.8, the pinned FMZ ZIP, and the public caches from the first replay. From `crypto-trader-skills`, run:

```powershell
python -m research.delta_fmz_priced_replay fmz.zip reference.json later.json research/delta-fmz-priced-replay.json
```

The published JSON records candle and source digests, entry and protective exit counts, win rates' inputs, costs, and coverage reasons. The **Delta backtests** worksheet contains the BTC, ETH and pooled results.
