# Sixth-round FMZ native evidence

The source audit covers 454 IDs from the round-five FMZ native, implicit
strategy, and source-data backlog. It pins the archive, hashes each document
and extracted block, and records line numbers for order calls and runtime
bindings. Python blocks also have AST checks. An exclusion requires a
source-reviewed utility designation or an explicit non-trading lifecycle.
Missing feeds, parameters, parsers, or framework bindings leave strategies
pending. The nineteen indicator declarations with actual strategy-order
calls have a separate declaration-conversion disposition. [Source audit](fmz-native-round6-audit.json)

The native JavaScript variants replay independently against Binance spot BTC
and ETH in the existing Reference and Later windows. The pinned WASM broker
uses candle-derived fills. Its allowed market requests bind to the pinned
historical tapes. The isolated Windows AppContainer denies outside filesystem
and network access. Archive configuration, fixed input changes and source
hashes are recorded. Cash and inventory reconcile through the final native
account snapshot, and closed lots use FIFO attribution. [First JavaScript pass](fmz-native-javascript-round6.json) · [Additional JavaScript pass](fmz-native-extra-round6.json)

- ID 5632 uses the archived random-sizing rule with fixed seed 5632 and
  one-minute sampling. The isolated order fixture checks market-entry fees
  against actual simulated debits. The source sizes can fall below published
  spot minimums, making the result specific to the simulator.
- IDs 619, 4543, 4922 and 4927 use settings from source-matched public
  previews. Their independent runs begin with empty local persistence and no
  operator commands. ID 619 models the minimum quote amount checked by its
  source with the historical public instrument minimum notional.
- IDs 4543 and 4922 start with attributed cash and base inventory because
  their original logic requires existing holdings. The seed uses the last
  complete base candle available before the replay starts. The inherited
  holdings carry no simulated entry fee. The account and expected positions
  have to reconcile after actual archived rule fills.
- ID 4345 retains hourly and daily market reads. Its public-source Bollinger
  variant hashes the public Binance daily history used for warm-up and uses
  one hour for the missing polling parameter. Its archived hardcoded LTC
  pair remains replaced by the named study pair.
- The remaining polling changes, position and pricing assumptions appear in
  each report. Realized drawdown starts from the study's 10,000 USDT
  reference equity. Open lots stay unsettled.

The native Python report retains verified no-fill sequences when their source
condition can be independently bounded. For ID 697, the highest candle in
each window stays below the 5% trigger even when the first candle's low is
used as the initial price. All four engine wallets also reconcile. ID 1098
has a separate closed-minute TA-Lib Bollinger variant using its source-matched
parameters and next-minute market fills. ID 472 uses complete hourly bars
formed from the pinned five-minute tape and preserves the source's terminal
hold outcome. The closed-bar variants apply the public minimum notional and
the study's fees and execution allowance. [Native Python receipts](fmz-native-python-round6.json) · [Bollinger receipts](fmz-native-bollinger-round6.json) · [Keltner receipts](fmz-native-keltner-round6.json)

ID 1203 preserves both archived quote gates and the matched 0.5 LTC
quantity. This variant uses synchronized Binance BTC/USDT, LTC/USDT and
LTC/BTC top-of-book quotes during two 00:05–07:55 UTC windows. Both
directions stayed below the archived fee hurdle in all 4,277 accepted
snapshots. The two rows have no fills and a blank win-rate denominator.
[Triangle receipts](fmz-native-triangle-round6.json) · [Historical quote schema](https://docs.tardis.dev/downloadable-csv-files)

To reproduce, use the same pinned FMZ archive and two verified round-five
AppContainer directories. Stage the first pass with `--initial`. Use a
separate AppContainer directory for the additional pass and fetch the public
daily windows and matched parameter page snapshots before staging. Rerun the
isolation probe for each directory and use the generated worker with the
wanted IDs. Run `stage-fee-fixture` plus the bundled market fee worker in the
first AppContainer for ID 5632. For ID 619 select the separate
`round6-native-minimum-worker.cjs` launcher input.

```powershell
python -m research.fmz_native_round6_audit $archive research/fmz-native-round6-audit.json
python -m research.fmz_native_round6_replay stage javascript $first scratch.json --initial --scratch $workspace --work $publicInputs
python -m research.fmz_native_round6_replay stage-fee-fixture javascript $first scratch.json
python -m research.fmz_native_round6_replay stage javascript $additional scratch.json --scratch $workspace --work $publicInputs
python -m research.fmz_native_round6_replay finish javascript $first research/fmz-native-javascript-round6.json
python -m research.fmz_native_round6_replay finish javascript $additional research/fmz-native-extra-round6.json
python -m research.fmz_native_round6_replay stage python $pythonOffline scratch.json --scratch $workspace
python -m research.fmz_native_round6_replay finish python $pythonOffline research/fmz-native-python-round6.json
python -m research.fmz_native_round6_bollinger $archive $pythonOffline research/fmz-native-bollinger-round6.json
python -m research.fmz_native_round6_keltner $archive $pythonOffline research/fmz-native-keltner-round6.json
python -m research.fmz_native_round6_triangle $archive $spotQuotes $publicInputs research/fmz-native-triangle-round6.json
python -m pytest -q tests/test_fmz_native_round6_audit.py tests/test_fmz_native_round6_bollinger.py tests/test_fmz_native_round6_keltner.py tests/test_fmz_native_round6_triangle.py tests/test_fmz_native_round5.py
```

[FMZ historical matching](https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching) · [FMZ runtime functions](https://www.fmz.com/user-guide/strategy-framework-and-api-functions/global-functions) · [Binance public REST market data](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)
