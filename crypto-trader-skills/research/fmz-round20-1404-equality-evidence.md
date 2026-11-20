# FMZ #1404 mixed-type equality check

The archived Dual RSI Breakthrough Strategy saves BTCUSDT with a
3-minute chart and a 1-minute base on Binance USD-M from 2023-12-19 to
2023-12-26 UTC exclusive. The BTC and separate ETH replay inputs each
have 3,360 chart bars and 10,080 positive-volume base bars. The archived
Pine v4 text has a dotted 50,000-capital assignment and a conditional
fractional assignment into an integer stop variable. The diagnostic
moves the capital literal to the declaration and casts the integer stop
input to float. The original default remains 250 ticks.
[Pinned source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%88%A9%E7%94%A8%E5%8F%8C%E5%90%91RSI%E7%AA%81%E7%A0%B4%E7%AD%96%E7%95%A5Dual-RSI-Breakthrough-Strategy.md) · [FMZ strategy page](https://www.fmz.com/strategy/436754)

The positive three-bar control isolates the `bool == 1` expression.
Pine Compat v4 evaluates that expression as false for a true series
value, input and literal. The v5 route evaluates it as true at the same
observations. The comparable `bool == true` and integer `1 == 1` controls
agree in both Pine versions. The archived `buy==1` and `sell==1` expressions
therefore keep its decision state at zero in the v4 replay. The same
literal expressions toggle that state in v5, and explicit boolean
conditions yield the same v5 output. The buy and sell indicator series
themselves agree. The complete 1-minute base reproduces the chart-only
orders in the v5 comparison.

| Market | v4 chart-only closes | v5 chart and full-base diagnostic |
|---|---:|---:|
| BTCUSDT | 8 short | 4 long, 4 short |
| ETHUSDT | 13 short | 6 long, 6 short |

The FMZ tutorial documents permissive mixed-type comparison using a
numeric string example. It leaves this older runtime's bool/integer
equality open. The strategy remains pending until an authentic archived
FMZ trace or equivalent primary execution evidence resolves that case.
The diagnostic outcomes are kept outside strategy rankings.
[FMZ Pine comparison tutorial](https://www.fmz.com/digest-topic/9637) · [Pine v4 comparison operators](https://www.tradingview.com/pine-script-docs/v4/language/operators/#comparison-operators)

## Reproduce

Use the December 2023 official Binance 1-minute ZIPs and checksum receipts
listed in the evidence JSON. Save the pinned archive in
`Scratch/source-1404.md`. Reuse the Round 11 isolated runtime.
[Round 11 runtime](fmz-round11-magnifier-priced.md)

```powershell
python -m research.fmz_round20_1404_stage PublicInputs Scratch
Copy-Item research/fmz_round13_2864_runner.py Scratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py Scratch/probe_1216.py
Copy-Item research/fmz_round20_1404_probe.py Scratch/replay_1404.py
Copy-Item research/fmz_round20_1404_equality_probe.py Scratch/equality_1404.py
Scratch/sandbox.ps1 Scratch isolation.py '' 90
Scratch/sandbox.ps1 Scratch equality_1404.py '' 120
Scratch/sandbox.ps1 Scratch replay_1404.py '' 120
python -m research.fmz_round20_1404_evidence Scratch Evidence.json
```

[Pending disposition and reproduced receipts](fmz-round20-1404-equality-evidence.json)
