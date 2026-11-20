# FMZ #5252 weekly decision timing

The archive specifies BTCUSDT, a four-hour chart, a 15-minute base
period and January 1–24, 2024. The diagnostic uses the saved window and
replays ETH over the same period. Official Binance daily candles form
eight Monday-to-Monday weeks. They include four December weeks for
initialization and the full January 22 week to expose the lookahead
in the saved window. There are 144 decision bars per market.
[Pinned archive](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E8%87%AA%E9%80%82%E5%BA%94%E7%A7%BB%E5%8A%A8%E5%9D%87%E7%BA%BF%E4%BA%A4%E6%98%93%E7%AD%96%E7%95%A5Adaptive-Moving-Average-Trading-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/442550)

The normalized Pine v2 diagnostic explicitly declares three recursive
series and adjusts legacy aliases and visual arguments. The original
function's last line returns its Ehlers SuperSmoother value. The DEMA
selection earlier in that function has no effect on its returned
series. An independent Ehlers recurrence from weekly opens and closes
matches every value that the normalized engine feeds into both entry
conditions. Archived integer division also gives a zero-period Hull
input and no long signals in the diagnostic. Both price-less exits are
inert under the tested compatibility runtime.
[Legacy Pine multiline function results](https://www.tradingview.com/pine-script-docs/v4/language/declaring-functions/#multi-line-functions) · [FMZ exit requirements](https://www.fmz.com/doc/9293#strategy.exit)

The legacy request makes the final weekly result available from that
week's first candle. Comparing visibly available confirmed values
changes 41 BTC and 100 ETH short-entry flags. The first simulated BTC
entry moves from January 8 at 04:00 UTC to January 15 at 00:00 UTC. The
first ETH entry moves from January 1 at 04:00 UTC to January 8 at
00:00 UTC. The archive does not establish a causal policy for its weekly
series. Catalogue status stays pending, with timing evidence only.
[Legacy TradingView lookahead behavior](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lookahead)

## Reproduce

Use the pinned source as `PyScratch/source-5252.md`. The report lists
the official Binance daily archives and the January 15-minute inputs.
Reuse the Round 11 Pine Compat runtime and isolated Python launcher.
[Historical runtime and input staging](fmz-round30-1070.md)

```powershell
python -m research.fmz_round30_1070_stage PublicInputs PyScratch
python -m research.fmz_round31_5252_stage PyScratch PublicInputs
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round31_5252_probe.py PyScratch/probe_5252.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 45
PyScratch/sandbox.ps1 PyScratch probe_5252.py '' 90
python -m research.fmz_round31_5252 PyScratch Evidence.json
```

[Verified timing receipts](fmz-round31-5252-evidence.json)
