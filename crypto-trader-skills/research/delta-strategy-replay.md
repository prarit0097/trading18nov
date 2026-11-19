# Delta historical strategy replay

The workbook's **Delta backtests** tab contains results for 23 Sep–20 Oct 2026 and 21 Oct–3 Nov 2026, inclusive in IST. The 13 directional rules run separately for BTCUSD and ETHUSD. The combined row pools their closed trades and groups same-time exits before calculating drawdown. The later window is a chronological comparison for these rules.

Each entry decision uses closed 5-minute bars. A trade is modeled at the next opening price with positive traded volume. The main panel exits at the opening price ten minutes later. Fixed-hold exits lacking a traded bar are counted separately. Each trade uses a fixed $1,000 gross entry notional. Pairs divide it equally between their two legs. Independently replayed tests start with $10,000 for drawdown calculations. After-fee P&L deducts 5.9 basis points per side on each fill. After-all-cost P&L also deducts 3 basis points per side for the modeled spread and slippage. Drawdown uses realized cash changes at the modeled exit times. Intratrade drawdown, funding, queue fills, leverage, shared margin and demo account constraints are outside the model.

**Test coverage** gives all 6,184 catalogue entries a status. The panel ran 13 previously defined directional rules, six relative-value rules, four source-linked Jesse entry/exit ports, 61 TA-Lib candlestick detectors with a standardized direction and exit, and one always-long baseline. The Jesse ports use a 5-minute timeframe and standardized execution. The source-signal variant uses the source's indicator exits and the second variant uses the ten-minute exit. The ports use local EMA/Wilder smoothing and the Donchian port uses a previous 20-bar channel. Open positions at the window boundary are reported as unsettled. TA-Lib scores are mapped by sign to direction, including names whose scores can be nonzero without a directional prediction. Catalogue status records the strategy classes that still require a source adapter, order model or different dataset.

## Reproduce

Relative-value results come from this simulator's implementation. It uses the last closed bar and the close 12 bars earlier to rank five coins. Both rank extremes choose the alphabetically first symbol on ties. The ratio tests share the five-coin input availability gate. Compare results within this replay since the cross-sectional counts differ from the earlier exploratory report.

Install `TA-Lib==0.6.8` in the research environment. From the `crypto-trader-skills` directory, the existing `research.delta_october_comparison` module can populate the reference cache using `--cache`. That download is verified against the public candle digests in the archived comparison. Then run:

```powershell
python -m research.delta_strategy_replay reference.json later.json replay.json --fetch-later
```

The later cache is fetched only if absent. The result JSON records both windows' public candle digests and traded-bar counts. The combined reference panel is regression-checked against the published gross counts and mean returns for all 13 original rules.
