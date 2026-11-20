# Fourth-round FMZ native and MyLanguage replays

The review starts with the 487 pending FMZ native and formula IDs in commit `fd4ad038`. It adds 120 rows for 20 IDs. Seventeen closed lots and three opened positions with no closes. The audit links each ID to its pinned source digest, declared archive languages, prior blocker, and any new receipt. Each tested ID has six rows covering BTC, ETH and both independently simulated books in the Reference and Later windows. Reference spans 23 September–20 October 2026 IST. Later spans 21 October–3 November 2026 IST. [Coverage audit](fmz-native-round4-coverage.json)

## MyLanguage signals

Twelve source-backed variants use complete UTC chart bars from Binance USD-M perpetuals. The rules evaluate at the chart bar's close and execute at the next minute open when that minute had trades. The translation applies source-recovered and archived parameter values, source instruction order, and the position filter where present. Some sources require an inverse contract, a dated contract, a different asset, a specific order price convention or a dynamic quote-to-contract conversion. Each variant records its substitution. Fixed stakes are 1,000 USDT per position, with twice that on ID 4392's short side to preserve the source's ratio. Quote funding at a settlement boundary applies to a position carried into that boundary, including a position closed at that instant. Positions still open are unsettled. [Formula results](fmz-mylanguage-round4.json) · [FMZ MyLanguage semantics](https://www.fmz.com/doc/9480) · [Binance data archive](https://github.com/binance/binance-public-data)

The formula report records each trade's side, times, prices, size, fees, execution allowance and funding. The causal channel fixture varies a current-bar extreme that must be excluded from the calculation. A second fixture independently checks a reversal against two next-open fills and the signed carry paid at their boundaries.

## Native spot engines

The isolated native workers start each BTC or ETH scenario with 10,000 USDT and zero spot inventory. They serve only the named public Binance spot inputs through the pinned broker's history callback. One-minute history uses the checksum-verified Binance ZIP files and the instrument precision from the public FMZ spot response. Five- and fifteen-minute trials reuse the verified native spot tapes. The reports document the archive chart period, base tick interval, parameter page evidence, runtime or broker substitutions, account snapshots and completed order history.

The public FMZ tutorial's spot execution template supplies the order lifecycle for selected calls to `$.Buy`, `$.Sell`, `$.GetAccount` and `$.CancelPendingOrders`. The template code and source page are hashed. The variant records its direct limit-order mode, 0.10 USDT price offset, one-unit order cap and one-second retry. Where an archived template setting supplies a different value, that archived value takes precedence. ID 1309 converts Binance's minimum notional to base quantity at its current quote so the template can stop retrying a residual order below the venue minimum. [FMZ spot template tutorial](https://www.fmz.com/bbs-topic/483)

Venue and currency substitutions are part of the scenario label. Candle-based native execution can approximate limits and grid fills at the simulator's synthetic quote path. Quote spread, queue position and market impact inputs are absent. The adapter keeps actual source order sizes and closes lots in FIFO order. Separate read-only snapshots around Python market orders confirmed the broker charges the base fee on filled turnover for market buys. The Python verifier uses that accounting and tests it independently. The JavaScript market-buy receipt model uses the prior native fee conversion. [Python results](fmz-native-python-round4.json) · [JavaScript results](fmz-native-javascript-round4.json)

The fee-only P&L uses 5.9 bp per side. The all-cost estimate adds 3 bp per side and signed funding when the product is perpetual. Realized drawdown uses the closed P&L path and the study's 10,000 USDT reference equity. Some accepted native cases validate a funded entry and have no closed lots. Their win rates have no denominator.

## Reproduction

Use the pinned archive, the previous native scratch inputs, the checksum-verified Binance cache, the archived public parameter receipts and a separate AppContainer root. Place the additional source-matched parameter receipt in `round4/native-params/receipt.json` below scratch. The audit and formula manifest record the matched page URLs and response hashes. Retrieve the public template tutorial response as `fmz-template-tutorial.html` in the AppContainer root. Run the previous Python and JavaScript filesystem and no-network probes in that root before the strategy workers. The current receipts record both denials. [Prior native replay setup](fmz-native-expanded-replay.md)

~~~powershell
python -m research.fmz_mylanguage_round4 $scratch research/fmz-mylanguage-round4.json
python -m research.fmz_native_round4 stage $scratch $offline
python -m research.fmz_native_round4 stage-js $scratch $offline
~~~

Copy `fmz_native_python_worker.py` and `fmz_native_python_round4_worker.py` into `$offline`. The Python native runner uses the pinned loader and binary from the earlier pass, with pandas, NumPy and TA-Lib staged as local dependencies. Run the staged jobs in the AppContainer. Pass the desired IDs to the worker and keep its JSONL receipts with the staged inputs. Run the staged Node script with the same filesystem restrictions. Assemble the selected trials and verify the audit using the following commands.

~~~powershell
python -m research.fmz_native_round4 finish $offline research/fmz-native-python-round4.json
python -m research.fmz_native_round4 finish-js $offline research/fmz-native-javascript-round4.json
python -m research.fmz_native_round4_coverage $scratch research/fmz-native-round4-coverage.json research/fmz-mylanguage-round4.json research/fmz-native-python-round4.json research/fmz-native-javascript-round4.json
python -m pytest -q tests/test_fmz_mylanguage_round4.py tests/test_fmz_native_round4.py
~~~
