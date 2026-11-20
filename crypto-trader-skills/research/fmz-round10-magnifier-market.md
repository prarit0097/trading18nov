# Round 10 FMZ market-order Bar Magnifier replay

Two preserved Pine strategies completed eight BTCUSDT and ETHUSDT replays
on public Binance USD-M history. ID 4721 used a 45-minute chart and
five-minute broker input. ID 5520 used a 60-minute chart and ten-minute
broker input. Both sampled 2026-08-01 to 2026-09-01 and 2026-09-01 to
2026-11-01 UTC, with independent starting capital in each window.
All 106 opening quantities and all 106 closing lots reconcile. No final
positions were open. The twelve result rows include BTC, ETH and pooled
independent accounts for each of the two windows per strategy.
[Replay output](fmz-round10-magnifier-market.json) · [Prior archive provenance](fmz-round7-magnifier.md)

The replays use the original Pine programs after removal of the FMZ host
metadata wrapper. ID 4721 keeps its 10,000-USDT account, 10% equity sizing,
0.075% commission per side, one tick of slippage and one-tick limit
verification. ID 5520 keeps its 1,000-USDT account, 100% equity sizing,
0.1% commission per side and fill-triggered recalculation. The broker
price grid is 0.1 USDT for BTCUSDT and 0.01 USDT for ETHUSDT. Both use a
0.001 base-asset lot step. Reported drawdown follows realized equity at
the chart-resolution fill timestamps. Funding is outside the replay model.
[TradingView strategy properties](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/)

## Broker verification

The local patch uses the pinned Pine Compat Runtime's existing
same-bar quantity calculation at the next market-order fill as well.
It marks equity at execution, reserves the opening commission and rounds
to the market lot. This fixes the demonstrated mismatch between signal
and fill prices in the stock release. The patch scope is the market-order
path. The traded windows passed a minimum-equity and maximum-price check
so order intent cannot round below one lot before the fill calculation.
[Broker patch](fmz-round10-magnifier-market.patch) · [Upstream MIT license](https://github.com/helenananaa/pine-compat-runtime/blob/c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc/LICENSE)

Both fixtures used identical input candles. The unmodified pinned release
failed six quantity and settlement checks. The patched build passed all
twelve, covering a 100-to-200 next-open gap, fee reservation, lot rounding,
reversal, exact one-tick trade-through at the original limit price, and
fill-triggered recalculation on the lower-timeframe path. The ordinary
OHLC path hit a 105 target in the adverse-ordering fixture. The complete
lower-timeframe path hit a stop and filled at 94. Across the archived
replays both API entry points produced identical ledgers and reported zero
fallback diagnostics.

## Reproduction

Check out Pine Compat Runtime commit
c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc and verify that Cargo.lock has
SHA-256 3b55229fb85cafd2218cc4545d1d35b4a5278396f775e6a29fa6b9c8cbaf33ba.
Apply the recorded patch, then build with pinned Rust and locked crates.
The report records the Windows extension digest from the study build.
Build paths can affect the debug binary's bytes.

```powershell
git -C EngineCheckout apply /path/to/fmz-round10-magnifier-market.patch
# From EngineCheckout, with build output and caches in local scratch
rustup run 1.95.0-x86_64-pc-windows-gnu cargo build --locked -p pine-python
```

Under Scratch, install the published 0.3.3 Windows wheel in
baseline-runtime. Stage its package layout in patched-runtime and replace
that copy's pine_compat.pyd with the locally built pine_compat.dll.
Use the same isolated Python AppContainer launcher and denial checks
as the earlier FMZ Python runs. Place the original source-4721.pine
and source-5520.pine produced by the Round 7 archive prep in Scratch.
Use the six published Binance one-minute ZIPs and adjacent checksum files
listed in the report.

```powershell
python -m research.fmz_round10_magnifier_market stage Scratch PublicZips
Copy-Item research/fmz_round10_magnifier_market_fixtures.py Scratch/fixtures.py
Copy-Item research/fmz_round10_magnifier_market_runner.py Scratch/runner.py
Scratch/sandbox.ps1 Scratch fixtures.py baseline 90
Scratch/sandbox.ps1 Scratch fixtures.py patched 90
Scratch/sandbox.ps1 Scratch runner.py '' 240
python -m research.fmz_round10_magnifier_market finalize Scratch Report.json
```

The original strategy files, raw data and compiled engine are local replay inputs.
