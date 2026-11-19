# Four-coin breakout feasibility

This research checks how often the four-coin Trade 1 batch could start if each entry required a confirmed breakout. It uses public Delta India testnet five-minute traded candles from 21 October to 17 November 2026 inclusive in UTC. The test uses BTCUSD, ETHUSD, SOLUSD, DOGEUSD and XRPUSD.

Reproduce the worker's long breakout observation at each five-minute close. Require a complete 21-bar window, strictly positive historical mean volume and a last close above the maximum high of the previous 20 bars. Require valid observations for all five coins at each timestamp. Exclude 100 of 8,064 timestamps with incomplete inputs. Relative volume is measured against the previous 20 bars.

| Condition | First 14 days | Last 14 days | Total |
| --- | ---: | ---: | ---: |
| Complete five-coin observations | 3977 | 3987 | 7964 |
| At least one READY coin | 526 | 515 | 1041 |
| At least four READY coins | 75 | 64 | 139 |

Requiring four READY coins yielded 139 of 7,964 timestamps (1.75%), on 26 of 28 days. Combining successive qualifying closes at most ten minutes apart yields 107 groups. Requiring at least four READY coins that also had relative volume of 1.5× or more yielded 48 timestamps.

These counts measure signals before execution checks. Historical executable spreads, turnover rankings, required margin and simultaneous fills were not reconstructed. Outcomes, fees and P&L were not estimated here. A future candidate test should report the percentage of READY batches that pass live portfolio checks, independent batch/day counts, net P&L and win rate. The campaign's running policy was not changed for this analysis.
