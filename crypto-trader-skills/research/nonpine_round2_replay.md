# Non-FMZ follow-up using public trade prints and recovered runtimes

The baseline at `cb4745c` had 159 pending non-FMZ entries. The [follow-up manifest](nonpine_round2_replay.json) records a disposition for all 159. It uses the existing Reference and Later windows, with the same 23 September, 21 October and 4 November 2026 IST boundaries.

## Deribit trade-print scenarios

The public Deribit history endpoint returned atomic BTC and ETH `option_combo` and `future_combo` trades, with a separate simultaneous trade record for each leg. Day-level pages were split until neither `has_more` nor the 1,000-record limit remained. The adapter checks complete window coverage, unique print IDs, corresponding leg timestamps, and reconciliation of the signed leg cash flows to the reported combo price. Each page's manifest records the exact address and SHA-256 of its `result` object encoded as compact UTF-8 JSON. The results include each matched entry and exit print ID. [Deribit combo definitions](https://support.deribit.com/hc/en-us/articles/31424954956061-Combo-Books)

Each observed instrument starts flat. The first buy-side print at or above the study size is the entry price proxy. The first sell-side print for that same instrument at least 15 minutes later is the exit proxy. The process repeats after each sampled exit. Different instruments run independently and can overlap. The sizes are 0.1 BTC or 1 ETH of the option combination and $100 of dated futures notional per leg. Futures spreads containing a perpetual leg are excluded. A structure needs at least one closed pair across both markets and windows to count as recovered. Unmatched entries are reported separately. This model measures sampled trade-price round trips. It has no order-book availability, trader queue, expiry settlement model, collateral constraints or proof the researcher could have obtained the printed fills.

Option gross P&L sums signed premium changes across the legs in settlement coin. Dated inverse futures leg P&L is signed USD contract notional times `(1 / entry price − 1 / exit price)`. Realized P&L and costs are converted into USD at the closing print's index. Pooled rows add these USD cash flows at the individual close events. The model uses undiscounted options commissions of 0.03% of coin notional per leg fill with the 12.5% premium cap, or 0.05% of inverse futures notional per leg fill. The modeled execution allowance is 3 bp of absolute premium or contract turnover per leg fill. The print study omits combo fee discounts. It reports realized drawdown from a 10,000 USD reference base. [Deribit fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees) · [Inverse options](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options)

## Binance framework cases

- Freqtrade retries run the pinned sources in a no-network Windows AppContainer with explicit migration notes and both source hashes on accepted rows. The retry guard rejects callback exceptions and missing informative history. `ETH/BTC` data uses seven checksum-verified public spot 1-hour archives. The original P&L, realized drawdown, source intervals and funding conventions carry forward. [Previous Binance framework methods](nonpine_replay.md)
- The native Jesse KDJ run uses Binance perpetuals at 1× because the current Jesse spot broker rejects the source's stop loss at entry. The source's obsolete `self.capital` alias maps to Jesse's `self.balance`. Both comparison windows use 1D UTC bars, source risk sizing and modeled fees. The run excludes funding. [Jesse research backtest](https://docs.jesse.trade/docs/research/backtest)
- The legacy batch uses the pinned Zenbot and Gekko strategy callbacks on 15-minute BTC/ETH spot bars. Long or buy advice enters a 1,000 USDT spot position at the next traded open and sell advice closes it. Fees are 5.9 bp per side, with an extra 3 bp of realized turnover for execution. The isolated runtime uses Node 16.20.2 with native Tulind 0.8.20, and reads output lengths directly from TA-Lib's C/WASM API. The pinned Zenbot engine has no order branch for `sold`. Reported orders follow its `buy` and `sell` branches and the fixed stake model. [Original legacy replay model](delta-pending-catalogue-replay.md)
- The Hummingbot directional models use the pinned indicator thresholds and the source executor's 2% target, 3% stop, 45-minute maximum life, same-side five-minute cooldown and two-executor cap. The study uses confirmed 3-minute signals, one-minute next-open market entries, conservative gap stops, strict through-price targets and stop priority when a minute reaches both prices. Leverage is 1× with 1,000 USDT per executor. Funding uses public Binance settlement rates and hourly mark opens for events strictly inside the holding interval. Quotes and queue details remain outside the model. [Hummingbot backtesting](https://hummingbot.org/dashboard/backtest/)

Other cases retain the original missing data or source contracts in the manifest, unless a retry produced a more specific failure. Historical tests made no writes to the demo.

## Reproduce

Use the public scratch directory and dependency versions documented in the [first non-FMZ replay](nonpine_replay.md), then freeze the earlier `remaining-backtest-coverage.json` from `cb4745c`. Save each Deribit address in `deribit_pages` to the stated filename as compact UTF-8 JSON after retaining only the API `result` field. Save `ethbtc_inputs` into `binance/ethbtc` alongside a `manifest.json` with that same array.

```powershell
python -m research.nonpine_round2_deribit "$scratch/round2/deribit" "$scratch/round2/deribit-out.json"
Copy-Item research/nonpine_round2_freqtrade.py, research/nonpine_round2_hummingbot.py $scratch
& "$scratch/nonpine_sandbox.ps1" -Root $scratch -Script 'nonpine_round2_freqtrade.py'
& "$scratch/nonpine_sandbox.ps1" -Root $scratch -Script 'nonpine_round2_hummingbot.py'
python -m research.nonpine_round2_legacy prepare $scratch
Copy-Item research/nonpine_round2_legacy.mjs "$scratch/round2"
```

For the legacy worker, install `talib-web@0.1.3`, `keltnerchannel@1.4.3` and the earlier pinned Node libraries without npm lifecycle scripts in `round2`. Use the stock Node 16.20.2 Win x64 binary and [Tulind 0.8.20 Win x64 ABI 93 addon](https://tulipnode.s3.amazonaws.com/tulind/v0.8.20/Release/tulind-v0.8.20-node-v93-win32-x64.tar.gz), SHA-256 `ef0d2f5d88d0faf1ed53b11f22500bc5fc9f53e1befc5808904174a56854a276`. Launch `nonpine_round2_legacy.mjs` inside the same no-network AppContainer with `--preserve-symlinks-main --preserve-symlinks` and both files under the allowed scratch root. The flag avoids traversal of the protected drive root during module resolution.

```powershell
python -m research.nonpine_round2_legacy finish $scratch
python -m research.nonpine_round2_coverage $scratch research/nonpine_round2_replay.json
```
