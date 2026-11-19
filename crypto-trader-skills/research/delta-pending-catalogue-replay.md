# Remaining BTC/ETH source replay

This batch checks the remaining BTC/ETH-configured FMZ entries, plus the Gekko and Zenbot catalogue entries. Results use BTCUSD and ETHUSD Delta India testnet candles for 23 September–20 October and 21 October–3 November 2026 IST. Previously verified catalogue backtests remain in the workbook.

## Test contracts

- The PineTS adapter runs pinned Pine v5/v6 source using PineTS 0.13.1 and public data only. Imported libraries, outside market data, intrabar recalc switches and unsupported language versions are eligibility dependencies. The adapter rejects successful results that rely on wall-clock or realtime data or use an explicit negative history offset.
- The 15-minute replay aggregates three consecutive 5-minute candles, using the traded bars for OHLC. It requires the full group to be present and resets engine state across candle gaps. Any execution on an aggregate candle with no traded volume invalidates that strategy run. Only these failures are retried at 30 minutes using six consecutive 5-minute candles. The retry depends on fill validity, regardless of its P&L.
- PineTS uses its own OHLC intrabar execution rules and configured source exits. Its denominator is closed lots, so a partial exit can count as a closed lot. Default entry sizing is standardized to $1,000 cash, while explicit source quantities and pyramiding are retained. Commission is set to 5.9 basis points per side inside the broker. Gross and after-fee lots are reconciled from fills and a separate 3 basis points per side is deducted for the modeled spread/slippage. This last cost is an ex-post estimate. The rerun does not use portfolio liquidation, funding or queue data. Maximum drawdown uses cumulative realized lot P&L from $10,000 starting equity.
- The Gekko and Zenbot adapters use the pinned strategy callbacks with their default parameters and 15-minute bars. Long/buy advice opens a $1,000 position and short/sell advice closes it, as in a spot-style strategy. Execution uses the next traded opening price, with the same cost assumptions. Debug examples, controls and strategies needing unavailable indicator libraries or framework modules have an explicit coverage status.
- The workbook uses the **Group** and **Replay interval** filters to identify methods. Entries without closed trades have blank win rates. Entries still pending require such dependencies as a Pine 2–4 runtime or verified migration, external series, native framework adapters, or orders with finer-grained fill evidence.

## Reproduce the FMZ batch

Install `pinets@0.13.1` without lifecycle scripts in a temporary work directory. Use the pinned FMZ archive and public Delta caches from the [previous replay](delta-fmz-replay.md). From the skill's root directory, run:

```powershell
python -m research.delta_pinets_catalogue prepare fmz.zip reference.json later.json work
node --permission --allow-worker --allow-fs-read=work --allow-fs-read=research/delta_pinets_worker.mjs research/delta_pinets_worker.mjs work/candidates.json work/candles.json /path/to/pinets.min.es.js 6 > work/out.jsonl
python -m research.delta_pinets_catalogue finish work research/delta-pinets-catalogue.json
python -m research.delta_pinets_catalogue prepare-retry reference.json later.json work work/retry
```

Place the npm package under the allowed work directory. Run the worker on `work/retry/candidates.json` and `work/retry/candles.json`, writing stdout to `work/retry/out.jsonl`. Finish that retry directory into a temporary JSON and apply `merge-retry`. The two result manifests include candle digests, catalogue IDs and actual source document SHA-256 values.

For the legacy run, use `git archive` at `ff5698f1ae6329bab5729f145c35a74161e82bac` for Gekko's `strategies` and `config` and at `52872fb4b5f9d10e2f891d95daec05da0b721ceb` for Zenbot's `extensions/strategies` and `lib`. Extract them under `work/gekko` and `work/zenbot`. In the catalogue, select rows whose source is `gekko` or `zenbot` and preserve their 1-based CSV data row as `id` in `work/legacy-candidates.json`. Install `lodash@4.17.23`, `@iarna/toml@2.2.5`, `zero-fill@2.2.4`, `numbro@2.5.0`, `bollinger-bands@3.0.2`, `stats-lite@2.2.0`, `mathjs@7.6.0` and `trend@0.3.0` into the work directory without lifecycle scripts. Run `delta_legacy_bot_replay.mjs` with that directory and write stdout to `work/legacy-out.jsonl`, then use `finish-legacy`.
