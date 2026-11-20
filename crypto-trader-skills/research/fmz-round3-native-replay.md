# Native FMZ replay, third round

The baseline is the pending catalogue in commit f66984c. The native broker report covers 471 pending IDs from the prior FMZ source screen. A separate MyLanguage report covers another 27 IDs with Pascal-tagged formula sources. The selected native and formula cases each have two windows and three market rows per window. Reference runs from 23 September through 20 October 2026 IST. Later runs from 21 October through 3 November 2026 IST. [Native broker results](fmz-native-round3.json) · [MyLanguage results](fmz-mylanguage-round3.json)

## Official JavaScript broker

The JavaScript WASM broker uses the pinned FMZ package and archived strategy code. Each script receives BTCUSDT or ETHUSDT Binance candles, with the q.fmz.com history callback serving only the recorded public tapes. The adapter retains source position sizes and recovers public parameter defaults only where the visible source prefix matches the archive. The spot model starts with 10,000 USDT and no coins. It reconciles cash, inventory and resting holds independently. Where the source assumption is a different market or timeframe, the result names the substitute. [FMZ JavaScript broker](https://github.com/fmzquant/backtest_javascript/tree/342baf9e74fdf83f3ef0b4c010200b1c3ddb9924) · [FMZ backtest modes](https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching)

The daily 120-bar moving-average strategy, ID 2515, preserves its archived 1h base. The callback skips repeated polls of the same daily bar because the source's next statement is a continue until its timestamp changes. Native time still advances, including any resting-order matches. The account receipt distinguishes the virtual snapshot time from the preceding synthetic market tick. The quoted order time determines the sequence of closed-lot drawdown.

The three-EMA strategy, ID 1183, keeps the archive's 300 USDT starting balance, 0.04 base-asset quantity, 1h chart and 15m base. The BTC trials submit no funded entries at the native 10× margin setting. ETH generated eight closing lots. The one-position ledger independently reconciles the simulated balance plus margin using market-order fills and public funding rates with the Binance index open at the settlement interval. The absolute free-cash difference is below 0.00001 USDT. Funding paid on positions still open at the boundary is in the broker reconciliation and stays out of realized trade P&L.

Modeled base costs are 5.9 bp per side. Net P&L includes an additional 3 bp per side execution allowance and signed closed-lot funding where relevant. Drawdown is calculated from realized close cashflows against the stated starting capital. Native fills come from the FMZ tick path generated from candles. Results with resting orders do not use a calibrated venue queue.

The Python environment and its file and outbound network denials are included in the receipt. The screened Python retries need complete boundary accounting. The C++ cases lack a complete order lifecycle or the required original OKEX expiry book and socket state. [FMZ supported runtimes](https://www.fmz.com/user-guide/backtesting-system/supported-languages-and-exchanges)

## MyLanguage formula translations

Eight formulas have a labeled linear perpetual variant. The adapter applies their source signals to Binance USD-M data, uses a fixed 1,000 USDT quote stake at 1×, starts flat with warmed indicators, and submits each accepted close-confirmed signal at the next observed minute open. It applies the source's ordering and one-position filtering where present. For the dated inverse or spot archives, the product substitution makes these directional scenario results. Native tick execution, original lot values, queue effects and collateral currency are outside this model. ID 467 repairs one malformed parenthesis in the source's typical-price expression. ID 621 omits its notification-only hook. [MyLanguage execution and signal rules](https://www.fmz.com/doc/9480)

Signals are evaluated only on complete UTC-aligned chart candles in the two study windows. The replay charges funding before an exit at the same funding boundary and applies Binance mark opens with the corresponding published rate. Gross, fee-only and fully net figures use each individually reconciled lot. Positions open at the boundary remain unsettled. [Public Binance archive](https://github.com/binance/binance-public-data)

## Reproduce

Use the prior native work directory and pinned FMZ archive from the expanded replay. The new manifests contain exact public source digests, verified source default checks and market input URLs and hashes. Place the public FMZ response bodies and the input index in the local round3-native scratch directory. The input index groups feeds by venue, suffix, candle seconds, coin and window start. Each group lists the filenames and URLs of its public response bodies. Consecutive public pulls sometimes include a partial overlap bar. The stage uses the complete next response's bar only when its open agrees and its range and volume include the earlier partial bar. [Previous native setup](fmz-native-expanded-replay.md)

Run the stage command below. Run each selected JavaScript ID group through the previous no-network AppContainer launcher using the staged round3-worker.cjs and the same Node filesystem restrictions. Use a separate AppContainer for the Python worker, with the staged native-jobs.json and the prior official Python backend. Confirm the two isolation probes before loading any archived code. Keep only the intended receipts in the scratch root before assembling the report.

~~~powershell
python -m research.fmz_native_round3 stage $scratch
python -m research.fmz_native_round3 finish $scratch research/fmz-native-round3.json
python -m research.fmz_mylanguage_round3 $scratch research/fmz-mylanguage-round3.json
~~~

The formula script reads the recovered public argument receipt and checksum-verifies the Binance one-minute, funding and mark data from the same cache as the non-FMZ study. It evaluates the translated expressions locally. The demo remains paused during the offline research. [Binance cache preparation](nonpine_replay.md)
