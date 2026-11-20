# FMZ #3038 pre-entry bracket evidence

The published daily strategy runs across 371 official Binance USD-M days
from November 21, 2022 through November 27, 2023 UTC exclusive. The source's
one-week default depends on Pine's execution clock. The primary replay
passes the archived endpoint as the execution timestamp for each bar
through the runtime host. This preserves the original source and makes
the last seven days eligible. A constant substitution at the same
time produces identical primary broker output.
[Pinned strategy source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%9F%BA%E4%BA%8E%E4%BB%B7%E6%A0%BC%E9%97%B4%E9%9A%99%E7%9A%84%E8%B7%9F%E8%B8%AA%E6%AD%A2%E6%8D%9F%E7%AD%96%E7%95%A5Trailing-Stop-Loss-Strategy-Based-on-Price-Gaps.md) · [FMZ strategy page](https://www.fmz.com/strategy/433542) · [Pine execution time](https://www.tradingview.com/pine-script-docs/concepts/time/#timenow)

The source submits a buy limit and an absolute bracket without an
entry ID before the buy fills. Both engines fill a later exit when
the daily bar closes. A control explicitly attaches the bracket to
the source's sole buy order. Pine Compat then fills a stop on the
entry day, while both Piner backends still fill at the close. A second
control moves the limit and target in the direction that preserves
their price protection, and aligns the stop to the first exchange
tick that can meet its authored trigger.

Binance's actual minute path reaches both normalized targets after
the entries. The BTC limit is first eligible in the 15:03 UTC candle
on November 21. The target of 36,702.10 USDT is then reached in the
15:46 candle. ETH's 15:03 entry candle ranges across its target too.
Its 67,346 published raw trades reproduce the full candle, including
volume. Sequence IDs and timestamps are ordered. The export skips
316 IDs. The first eligible buy print is at 15:03:12.267 UTC, and the
recorded minute has no eligible target afterward. The next minute
reaches the target of 1,981.36 USDT. These are observed price-path
events supporting simulated orders, with no queue or bid/ask data.
[Binance USD-M archive formats](https://github.com/binance/binance-public-data#futures)

| Market | Normalized buy | First eligible bracket level | Named primary daily control | Unnamed daily exit, both engines |
|---|---:|---:|---:|---:|
| BTCUSDT | 36,338.60 | Target 36,702.10 | Stop 35,975.20 | 35,737.00 |
| ETHUSDT | 1,961.73 | Target 1,981.36 | Stop 1,942.12 | 1,933.44 |

The primary runtime uses signal-close sizing for the priced entry.
The fill-price calculation produces the same BTC quantity and a
different ETH quantity, 0.050 versus 0.049 in the primary runtime.
Both are independently reproduced with the archived 100 USD capital
and checksum-pinned previous-day Coinbase USDT/USD rates. The
published FMZ reference describes exit orders waiting for a pending
entry. Its public archive does not settle the exact behavior of the
unnamed pre-entry bracket with this host or the competing sizing basis.
Catalogue status remains pending with no performance rows.
[FMZ exit-order reference](https://www.fmz.com/doc/9293#strategy.exit) · [TradingView bracket semantics](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/#exits-for-multiple-entries)

## Reproduce

Save the pinned FMZ archive as `PyScratch/source-3038.md`. The report
lists official hourly and minute archives, checksums, the ETH raw
trade tape and the pinned Coinbase data inputs. Reuse the Round 11
isolated Python and Round 7 isolated Node environments.
[Round 11 pinned native runtime](fmz-round11-magnifier-priced.md) · [Round 7 pinned Node runtime](fmz-round7-magnifier.md)

```powershell
python -m research.fmz_round34_3038_stage PublicHours PublicFx PyScratch
Copy-Item research/fmz_round13_2864_runner.py PyScratch/replay_2864.py
Copy-Item research/fmz_round18_1216_probe.py PyScratch/probe_1216.py
Copy-Item research/fmz_round34_3038_runner.py PyScratch/probe_3038.py
PyScratch/sandbox.ps1 PyScratch isolation.py '' 45
PyScratch/sandbox.ps1 PyScratch probe_3038.py '' 90
Copy-Item PyScratch/3038-inputs.json,PyScratch/3038-source-variants.json NodeScratch
Copy-Item research/fmz_round34_3038_alternate.mjs NodeScratch/run_3038.mjs
NodeScratch/sandbox.ps1 NodeScratch run_3038.mjs '' 90
python -m research.fmz_round34_3038 PyScratch NodeScratch PublicMinutes PublicTradeTape Evidence.json
```

[Verified clock, fills and event receipts](fmz-round34-3038-evidence.json)
