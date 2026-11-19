# FMZ partial exits and stop-limit replay

This replay scans the pending BTC/ETH-configured entries in the pinned FMZ catalogue for partial exits and entries that declare both a stop and a limit. The comparison uses the same public Delta testnet 5-minute BTCUSD and ETHUSD candles as the [market-order](delta-fmz-replay.md) and [priced-order](delta-fmz-priced-replay.md) replays. The two windows are 23 September–20 October and 21 October–3 November 2026 IST. The workbook records the original archived interval beside each 5-minute port.

## Order and accounting assumptions

- A stop-limit entry has a waiting stop stage followed by a resting limit stage. An order whose stop is already crossed at submission can arm at that close. A stop reached intrabar arms the limit for later bars because the 5-minute extremes do not establish the sequence. An open-market activation can fill at that open or later within that bar under the limit rules. Replacing an armed order at changed levels re-evaluates the new stop, and an unchanged order retains its stage.
- A resting limit needs penetration unless already executable at the open. The stop is charged first if a stop and target for the same tranche are both touched intrabar. Known opening fills precede intrabar fills. When OHLC cannot sequence competing orders, the entry stays pending in coverage.
- A bracket exit reserves a share of the original position. A market partial exit using a percentage takes that share of the remaining position. Absolute exit sizes use underlying units under the standardized $1,000 entry. Each bracket ID produces at most one reserved fill per live position. Reservations are capped by the remaining size. Exit distances specified in ticks use the same Delta tick assumptions as the priced-order test.
- The regular win rate and trade P&L columns use fully closed positions. All exit legs are combined per position. The rightmost realized cash columns also include fills on positions with a remainder still open at a window boundary or data gap. Drawdown tracks those cash changes at their recorded timestamps, including entry fees. Mark-to-market P&L on residual position size is excluded. A zero-trade win rate is blank.
- Costs use the same 5.9 bp per side fee and 3 bp per side modeled spread/slippage as the earlier replay. Drawdown starts from $10,000. The candle model excludes queue priority, margin and funding. The model uses fixed entry notional and source exit sizing under those units.

**Delta backtests** contains individual and pooled results, order-family filters, completed position counts, fill counts and P&L. **Test coverage** records the pending reason for sources that require a native Pine state adapter, unsupported order parameters or more detailed execution data.

## Reproduction

Use the pinned FMZ ZIP, TA-Lib and the same public Delta candle caches from the preceding reports. Run from `crypto-trader-skills`.

```powershell
python -m research.delta_fmz_staged_replay fmz.zip reference.json later.json research/delta-fmz-staged-replay.json
```

The JSON records source document and candle digests, coverage, per-market fill counts and both P&L measurements.
