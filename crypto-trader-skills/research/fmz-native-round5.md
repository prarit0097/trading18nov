# Fifth-round FMZ native and formula replays

The scope is the 467 native and formula IDs that remain pending in the fourth-round catalogue. The replay scripts verify each selected document against the pinned FMZ archive and fourth-round digest. The report coverage arrays retain attempted cases and their disposition. Results use BTC and ETH books independently across the Reference and Later windows.

The native JavaScript and Python spot trials use the pinned FMZ engines and public Binance spot candles. Both Windows AppContainers denied outbound networking and reads outside the input directory during their isolation probes. The workers expose archived candles through an allowlisted historian callback. Python daily and four-hour warm-up candles are aggregated from the previously verified hourly tapes. The two native reports give the template variants, applied parameters, receipt hashes and end-state reconciliation for each attempt. [JavaScript receipts](fmz-native-javascript-round5.json) · [Python receipts](fmz-native-python-round5.json) · [Published spot order template](https://www.fmz.com/bbs-topic/483)

Native spot results start with 10,000 USDT and zero inventory per market. Scenario notes identify changes to source polling, sizing or grid state. Spot fills use the native simulator's candle-derived prices. The independent inventory ledger pairs lots FIFO and uses the native market-buy fee convention for the relevant engine. Drawdown places matched lots at the closing order's recorded placement time, the precision available in native order history.

The formula and JavaScript recipe trials use complete UTC Binance USD-M bars and execute at the first traded minute of the next bar. The models preserve archived position rules and use the stated funded margin or fixed-lot substitutions. They apply the prior channel definitions, directional FIFO accounting, fee and execution allowances, and signed funding at settlements carried into the close. MyLanguage variants that replace MULTSIG evaluate one eligible action per bar. [MyLanguage receipts](fmz-mylanguage-round5.json) · [JavaScript recipe receipts](fmz-native-recipes-round5.json) · [MyLanguage semantics](https://www.fmz.com/doc/9480) · [FMZ indicator source](https://www.fmz.com/bbs-topic/10136)

P&L is reported for closed lots. End-of-window inventory stays open and carries its separate fee and funding evidence. The fee-only view uses 5.9 basis points per side. The all-cost view adds 3 basis points per side for execution and incorporates signed perpetual funding. Drawdown runs on realized cash flows with the study's 10,000 USDT reference equity, and combined rows pool the two simulated books' closed lots.

Use the pinned archive and previous replay inputs to regenerate the formula and recipe reports. The native stage uses the detailed market specifications and setup from the fourth round, plus the public parameter receipts and two offline scratch locations. The launchers, dependencies and raw receipts stay in scratch. [Prior native setup](fmz-native-round4.md)

```powershell
python -m research.fmz_mylanguage_round5 $scratch research/fmz-mylanguage-round5.json
python -m research.fmz_native_round5_recipes $scratch $publicParams research/fmz-native-recipes-round5.json
python -m research.fmz_native_round5 stage javascript $scratch $offlineJs
python -m research.fmz_native_round5 stage python $scratch $offlinePy
```

Run the generated workers with the prior no-network launchers for the selected IDs. Use `fmz_native_python_round5_warm_worker.py` for 4860 and 5162. Each worker produces local JSONL order receipts. The final reports store native order columns in the order given by `order_fields`.

```powershell
python -m research.fmz_native_round5 finish javascript $offlineJs research/fmz-native-javascript-round5.json
python -m research.fmz_native_round5 finish python $offlinePy research/fmz-native-python-round5.json
python -m pytest -q tests/test_fmz_native_round5.py tests/test_fmz_native_round4.py tests/test_fmz_mylanguage_round4.py
```
