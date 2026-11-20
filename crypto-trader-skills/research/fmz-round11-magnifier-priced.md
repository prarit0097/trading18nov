# Round 11 FMZ priced-stop Bar Magnifier replay

The unchanged FMZ Pine sources 5117 and 5514 each produced four verified
historical replays on Binance USD-M. The archive names BTC_USDT. ETHUSDT
is an explicitly labeled cross-asset study on the same venue.

Both strategies use market data for 2026-08-01 to 2026-09-01 and
2026-09-01 to 2026-11-01, in UTC with exclusive ends and fresh capital
for each asset and window. ID 5117 uses 60-minute chart candles and
10-minute broker input. ID 5514 uses 15-minute chart candles and
two-minute broker input with the pinned PineForge chart-boundary
ownership rule. Where a two-minute interval crosses a chart boundary,
the interval belongs to the parent containing its last minute. At an
affected parent endpoint the broker also receives the actual chart open
or close as a point price. The one-millisecond timestamp adjustment
orders a straddler within its owning parent. Point prices come directly
from recorded chart opens and closes. Coverage uses public Binance minute data.
[TradingView timeframe mapping](https://www.tradingview.com/support/solutions/43000669285-what-is-bar-magnifier-backtesting-mode/) · [Pinned PineForge ownership implementation](https://github.com/pineforge-4pass/pineforge-engine/blob/665fc4ddc024951dd1c911ad5de9839a5c91e2e4/include/pineforge/source/magnifier_intrabars.hpp)

Both of the sources' daily request literals receive the same pinned
Binance daily series. It was cross-checked against the available
minute history. Observer plots prove the preceding daily open-context
high and closing value on all 22,072 eligible chart bars. The executable
signal source is unchanged after removal of the FMZ comment wrapper.
The original 10 percent equity sizing, one tick of slippage,
one-tick limit verification, and 0.075 percent per-side commission
were retained. The source uses only long stop entries and supplies
no named entry OCA group. The additional named-OCA control confirms
that explicit-order sibling cancellation survives the patch.

The extension builds from Pine Compat Runtime source commit
c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc, the immutable Round 10
market patch, and the separate priced-stop patch with SHA-256
d67d6891f3aa13b38550d836d48b5da78e81c398d4c0881921e553aee6c532e1.
Rust 1.95.0 Windows GNU built the Python ABI3 extension with Cargo.lock
enforced. The market-only baseline failed the two priced-stop
quantity controls and the additional reversal opening-quantity
control. The priced patch passed all 22 checks, including fee
reservation, lot rounding, explicit quantities, reversal, v5
absolute-vs-relative exit precedence, OCA, and all 12 market patch
regressions. The OCA control verifies unchanged explicit sizing.
Default-percent stops with related OCA reductions remain outside
this patch's demonstrated scope.
[Pine Compat pinned source](https://github.com/helenananaa/pine-compat-runtime/tree/c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc)

The report contains 65 verified opening fills, 63 settled closes
and two ending open positions. Each pending stop is reconstructed
from the archived high-breakout rule. The audit independently
matches its eligibility, first lower input crossing, native tick
rounding, slippage, quantity, fees and cash settlement. The 12
result rows are realized P&L and drawdown. Native fill time is
recorded at chart resolution. Funding is outside the replay model.

## Reproduce the study

Use the six official Binance one-minute ZIPs and their checksum files.
The staging command also expects the two pinned 2026 daily feed envelopes
from the Round 7 staging directory. It validates both daily file digests,
checks daily prices against the minute inputs and checks the hourly
Bar Magnifier payloads against Round 10. Place the archived source-5117.pine
and source-5514.pine in Scratch. The replay checks the original script hashes
before removing the FMZ comment wrapper.
[Round 7 source and daily preparation](fmz-round7-magnifier.md) · [Round 10 market proof](fmz-round10-magnifier-market.md)

In an isolated checkout of the pinned Pine Compat source, apply the
Round 10 market patch first and build the baseline from the frozen Cargo
lock. Apply the Round 11 patch to that same source state and build the
priced variant. Keep the resulting Python package copies under
market-runtime and priced-runtime in Scratch. In each package's
pine_compat directory use the generated pine_compat.dll as
pine_compat.pyd. Both builds use the ABI3 layout of the published
Pine Compat 0.3.3 package. The output records both local binary digests.
[Incremental stop patch](fmz-round11-magnifier-priced.patch) · [Pine Compat release](https://github.com/helenananaa/pine-compat-runtime/releases/tag/v0.3.3)

```powershell
# From the independent engine checkout after applying each patch
rustup run 1.95.0-x86_64-pc-windows-gnu cargo build --locked -p pine-python
```

Use the same offline Windows Python AppContainer and denial probe as the
earlier FMZ studies. Run the market baseline and priced checks separately.
For the market regression fixture, expose the priced-runtime package
under the filename expected by the Round 10 fixture, patched-runtime,
within Scratch.

```powershell
python -m research.fmz_round11_magnifier_priced stage Scratch PublicZips Round7Scratch
Copy-Item research/fmz_round11_magnifier_priced_stop_fixture.py Scratch/stop_fixture.py
Copy-Item research/fmz_round11_magnifier_priced_controls.py Scratch/controls.py
Copy-Item research/fmz_round11_magnifier_priced_runner.py Scratch/runner.py
Copy-Item research/fmz_round10_magnifier_market_fixtures.py Scratch/regression.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch stop_fixture.py market 90
Scratch/sandbox.ps1 Scratch controls.py market 90
Scratch/sandbox.ps1 Scratch stop_fixture.py priced 90
Scratch/sandbox.ps1 Scratch controls.py priced 90
Scratch/sandbox.ps1 Scratch regression.py patched 90
Scratch/sandbox.ps1 Scratch runner.py '' 300
python -m research.fmz_round11_magnifier_priced finalize Scratch Report.json
```

[Verified results](fmz-round11-magnifier-priced.json)
