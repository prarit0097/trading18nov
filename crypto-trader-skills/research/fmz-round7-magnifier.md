# Round 7 FMZ Bar Magnifier replay

Five archived strategies completed historical BTCUSDT and ETHUSDT replays
with active lower-timeframe broker execution. The workbook report contains
30 rows across two independent windows per strategy, with separate BTC, ETH
and pooled results. The 20 asset-window runs consumed 154,944 intrabars on
9,768 chart candles. Each run reported zero fallback bars and its Piner
JavaScript and interpreter results were identical.

| Catalogue IDs | Archived chart | Injected bars | UTC dates |
| --- | --- | --- | --- |
| 59, 3254, 3843, 4167 | 1 day | 1 hour | 2025-01-01 to 2026-01-01 and 2026-01-01 to 2026-11-01 |
| 4601 | 1 hour | 10 minutes | 2026-08-01 to 2026-09-01 and 2026-09-01 to 2026-11-01 |

The date intervals are half-open. Binance USD-M archive checksums and a
complete UTC grid establish coverage. Ten-minute candles aggregate the ten
published one-minute candles in each interval. The two distinct sources
3254 and 3843 produced the same trades in these windows.
[Replay report](fmz-round7-magnifier.json) · [Binance archive specification](https://github.com/binance/binance-public-data)

## Fill and accounting model

The replay removes the FMZ host metadata wrapper and preserves the Pine
program. The host uses the earlier catalogue's BTCUSDT 0.1 price tick,
ETHUSDT 0.01 price tick and 0.001 minimum lot unit. It restores the Pine v5
zero-margin default where the archive omitted margins. The archive's
commission and slippage enter the Piner ledger. Gross P&L is reconstructed
from its fill prices, so configured slippage is already reflected in gross
P&L. Fee and net columns deduct the recorded commission. The workbook
drawdown is calculated from closed trades at each exit timestamp and the
report retains the broker's intrabar drawdown separately. The pooled rows
combine two independently funded accounts. Funding is outside the broker
model.
[Piner semantics](https://github.com/heyphat/piner/blob/main/docs/pine-semantics.md#9-bar-magnifier-use_bar_magnifier) · [Pine v6 margin defaults](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/)

## Verified limitations

- A synthetic broker fixture entered at 100 and took the 105 target under
  ordinary OHLC traversal. The complete 5-minute replay correctly saw the
  gap first and exited at 94. The fixture rejected incomplete coverage and
  the wrong target interval.
- ID 5520 requires fill-triggered script recalculation. With this flag and
  injected bars, the Piner fixture registered an inactive magnifier.
- IDs 4721, 5117 and 5514 set one-tick limit verification. Piner omitted the
  property and filled a limit that only touched the order price.
- ID 5540 specifies USD account conversion on a USDT instrument. The
  fixture produced the same account currency and sizing for USD and EUR
  declarations. Separate checksum-verified BTC/ETH aggregate-trade samples
  yielded all 8,640 ten-second buckets each but diverged from the official
  minute OHLCV. The report records the mismatch counts.

## Reproduction

Use the published file names and SHA-256 receipts in the report to stage
the Binance ZIPs and their adjacent `.CHECKSUM` files. Place the
`@heyphat/piner` 0.13.0 registry tarball at
`Scratch/piner-0.13.0.tgz` and extract its original `package/`
directory inside `Scratch`. The runner checks both the tarball and
engine bundle digests before import.

```powershell
python -m research.fmz_round7_magnifier stage Scratch PublicZips FMZ_ZIP research/remaining-backtest-round6-coverage.json
python -m research.fmz_round7_magnifier check-trades Scratch PublicZips
Copy-Item research/fmz_round7_magnifier.mjs Scratch/piner-replay.mjs
# Invoke the existing AppContainer launcher separately for these modes.
# The launcher's fourth argument is the wall-clock limit in seconds.
Scratch/sandbox.ps1 Scratch piner-replay.mjs fixture 60
Scratch/sandbox.ps1 Scratch piner-replay.mjs settings 60
Scratch/sandbox.ps1 Scratch piner-replay.mjs compile 60
Scratch/sandbox.ps1 Scratch piner-replay.mjs 'replay 59 3254 3843 4167 4601' 210
python -m research.fmz_round7_magnifier finalize Scratch Report.json
```

Use the same external-file and network denial probe as the prior isolated
FMZ replay and keep its `isolation-probe.json` in `Scratch`. The stored
replay receipt is byte-identical across independent reconstruction runs.
