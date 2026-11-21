# Remaining BTC and ETH backtests, round 48

One strategy received a verified historical result. The backlog falls from 179 to 178. Of the original 785 entries, 326 have verified historical scopes and 281 have verified exclusions. The workbook adds one performance row and reaches 5,678 tested catalogue entries.

## #1116 original Python Dual Thrust

The source runs unchanged against the named OKEX BTC-USD-190906 current-week contract on 1 September 2019, 06:00–22:00 UTC. The publisher supplies the strategy defaults but leaves the date and wallet unspecified. The replay uses an explicit 0.1 BTC starting wallet and reconstructs the one-minute tape from 45,240 recorded trades. The 54 empty minutes remain absent. FMZ models intraminute quote chronology and all observed taker fees are reconciled in BTC. [Author publication](https://www.fmz.com/strategy/21856) · [Historical feed reference](https://docs.tardis.dev/historical-data-details/okex-futures)

The nine filled orders produce four closed reductions, all losses after modeled fees. Gross P&L is −0.0001843734 BTC, modeled fees are 0.0000416454 BTC, and realized net P&L and max drawdown are −0.0002260188 BTC and 0.0002260188 BTC (0.2260%) respectively. One contract remains long at the terminal mark. The report includes the separately reconciled open exposure. [Native replay and wallet proof](fmz-native-round52-1116-dated-weekly.json)

## #6010 native history gate

OctoBot's archived market-making mode declares itself ineligible for the native backtest launcher. Its live producer can still initialize when reference and portfolio conditions hold and can replan after quote changes or fills. An exact offline event replay needs the authoritative book, reference updates and fill lifecycle. The scope remains pending. [Archived mode evidence](fmz-round59-6010-native-eligibility.md)

## #3184 reproducibility correction

Round 47's packaged producer indented generated top-level Pine statements incorrectly and its source fingerprint came from that generated file. The scratch run used the verified, correctly indented source. The producer now generates that source and checks each staged script's hash. All four fresh isolated modes reproduced the earlier execution receipts byte for byte. The six #3184 performance rows match the corrected report, including every win rate, P&L and drawdown. The historical Round 47 coverage checkpoint records the earlier report digest. The current report carries the corrected executed-source fingerprint. [Corrected evidence](fmz-round58-pine-cipher-divergence.json)

Delta Demo entry hold is active. The repository test suite passed 342 tests and 89 subtests. The workbook verifier compared prior backtest rows, all 179 coverage addresses and the new table boundaries.
