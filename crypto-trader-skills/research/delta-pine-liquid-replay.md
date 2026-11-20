# Binance USD-M replay of Pine strategies blocked by untraded Delta candles

The batch covers 351 FMZ catalogue entries that remained pending after the Delta replays reported an order fill on a candle without traded volume. It keeps the prior effective strategy timeframe at 5, 10, 20 or 30 minutes. The replay uses public trade-derived BTCUSDT and ETHUSDT perpetual candles on Binance USD-M. It covers 23 September–20 October and 21 October–3 November 2026, both inclusive in IST. Each exchange-aligned candle starts and closes within its window. The two windows are run independently.

The archive contains 8,064 five-minute candles per market in Reference and 4,032 in Later. Both markets have complete time coverage and traded volume on every candle. The result manifest records all ten archive URLs, the exchange-published SHA-256 digests, the aggregate candle digests and the source document digest for each result. [Binance Public Data](https://github.com/binance/binance-public-data)

The replay completed for 348 entries and returned 2,088 result rows. Of those entries, 347 recorded closed trades and one had no closes. ID 328 requires wall-clock time. IDs 1514 and 5755 call an unseeded random generator. All three are recorded as pending in the manifest.

PineTS 0.13.1 replays the pinned source using the existing native or legacy compatibility rules. The offline worker rejects fills on untraded candles and reconciles order fees and realized P&L independently. Default entry sizing uses 1,000 USDT and source quantities and pyramiding take effect when specified. Costs use the existing research assumptions of 5.9 basis points per side for fees and 3 basis points per side for modeled spread and slippage. Pooled rows combine realized lots by exit time. Drawdown starts from a 10,000 USDT reference equity. The run excludes funding, margin calls, liquidation, queue effects and new exchange orders.

Use the `market` and `market_data` fields to identify these results in comparisons. The use of another venue changes the candle path, volume, quote currency and symbol metadata. The same original dates and strategy timeframe establish an alternate historical replay without a new out-of-sample period.

## Reproduce

Use the pinned FMZ archive from the [native PineTS replay](delta-pending-catalogue-replay.md). Install `pinets@0.13.1` without lifecycle scripts in a local scratch directory. The Python preparation imports the same TA-Lib and NumPy dependencies as the [legacy migration](delta-pine-migration-replay.md). From the skill root, point `$scratch` at that local directory. Preparation downloads missing Binance ZIPs and validates them against the official checksums. The worker receives read-only access to the scratch candle and source inputs and the installed PineTS package.

```powershell
$run = "$scratch/liquid"
python -m research.delta_pine_liquid_replay prepare "$scratch/fmz.zip" $run
$manifest = Get-Content "$run/batches.json" | ConvertFrom-Json
foreach ($minutes in $manifest.job_minutes) {
    node --permission --allow-worker --allow-fs-read=$run --allow-fs-read="$scratch/node_modules" "$run/worker.mjs" "$run/$minutes/candidates.json" "$run/$minutes/candles.json" "$scratch/node_modules/pinets/dist/pinets.min.es.js" 5 > "$run/$minutes/out.jsonl"
    if ($LASTEXITCODE -ne 0) { throw "PineTS worker failed for $minutes-minute candles" }
}
python -m research.delta_pine_liquid_replay prepare-retry $run
foreach ($minutes in $manifest.job_minutes) {
    if (!(Test-Path -LiteralPath "$run/$minutes/retry-candidates.json")) { continue }
    node --permission --allow-worker --allow-fs-read=$run --allow-fs-read="$scratch/node_modules" "$run/worker.mjs" "$run/$minutes/retry-candidates.json" "$run/$minutes/candles.json" "$scratch/node_modules/pinets/dist/pinets.min.es.js" 1 > "$run/$minutes/retry-out.jsonl"
    if ($LASTEXITCODE -ne 0) { throw "PineTS serial retry failed for $minutes-minute candles" }
}
python -m research.delta_pine_liquid_replay finalize research/delta-pine-liquid-replay.json $run
```

Use a fresh `$run` directory for each full reproduction. The serial retry reruns timeout records with one worker to reduce CPU contention. It keeps the same source, candles, limits and broker configuration.

`coverage` in the result manifest contains one row for each catalogue ID, with the test status and the evidence or specific pending dependency. Each completed strategy has six result rows covering the two windows and both markets plus their combined lots.
