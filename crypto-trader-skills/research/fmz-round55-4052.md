# FMZ #4052 DCA replay with exact lots

The benchmark keeps the saved long bot on the archived 371-day Binance USD-M interval from November 14, 2022 to November 20, 2023 UTC exclusive. It evaluates the source's RSI and CCI filters at the last confirmed 5m, 15m and 30m close of each daily bar. The authored five resting buy levels span 0%, 20%, 40%, 60% and 80% below the entry reference. The saved default uses the 1.4% take-profit and disables its optional stop. BTCUSDT matches the archived market and ETHUSDT is a same-window comparison. [Archived FMZ strategy](https://www.fmz.com/strategy/432802)

| Market | Closed lots | After-fee win rate | Gross P&L | After-fee P&L | Closed-trade drawdown | Daily marked drawdown | Open lots |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 34 | 97.06% | 4,794.80 | 4,458.66 | 0.00 | 1,189.43 | 0 |
| ETHUSDT | 35 | 94.29% | 6,357.58 | 6,008.93 | 0.00 | 1,641.14 | 1 |
| Pooled closed-lot sequence | 69 | 95.65% | 11,152.38 | 10,467.59 | 0.00 | — | 1 |

Amounts are in USDT. After-fee outcomes apply a common 0.075% commission each side. A batch exit can realize a loss on one lot and a larger gain on another at the same timestamp. The closed-trade drawdown groups those same-time settlements, while daily marked drawdown includes the open position and posted fees. The final ETH lot of 3.321 entered at 1,961.21 and marked at 2,012.46. Its mark stays outside the closed results. Funding, spread, additional execution latency and live queue placement are outside the benchmark.

The saved Pine declaration left the account capital implicit. A later invalid property write set 50,000 and supplied all explicit order sizes. The portable benchmark puts that value in the declaration. A control leaves the wallet default and uses 50,000 as the order-sizing reference. Both controls give identical literal broker orders and closes. The date inputs remain in the compiled source. Its saved `within_window()` function returns true, so the archive's own timeframe determines the test interval. [FMZ parameter definitions](https://www.fmz.com/strategy/432802)

The fractional native broker left `8.88 × 10⁻¹⁶` ETH after closing two lots on August 29. `opentrades` then stayed at one through the end of the archive, suppressing later orders. An isolated six-bar fixture reproduces this with 3.374 and 4.626 ETH and confirms a normal return to flat in exact 0.001-unit lots. The verified run represents both markets in those whole lots with the corresponding point value. Off-grid buy limits round down and sell limits round up, preserving limit-price protection. Tick sizes are 0.10 BTCUSDT and 0.01 ETHUSDT. The narrow numeric tolerance only preserves input prices already on the grid. [Pine strategy order, fill and exit semantics](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/)

Each market has 106,848 confirmed 5m bars and 8,904 hourly bars. A stale BTC 5m archive disagrees with two November 10 hourly bars. The raw-trade-verified official daily 1m source from the [#3749 data check](fmz-round49-3749.md) restores exact hourly alignment after reaggregation. The finalizer rebuilds the indicators on their actual child bars and verifies every daily gate, all 136 grouped entry and exit events, each settled lot and all daily account snapshots. An at-touch control and a strict recorded price excursion past the limit agree for every scored event, with no simultaneous entry and exit ambiguity. The earliest supporting 5m bar is recorded in the JSON journal. [Binance Public Data](https://github.com/binance/binance-public-data)

## Reproduction

1. Stage the saved `source-4052.md` from catalogue commit `7853bb2bf262c4567ac238d3552d97f0e50cb801` and its pinned Pine runtime in the existing offline AppContainer.
2. Run `python -m research.fmz_round55_4052_stage SANDBOX HOURLY_ARCHIVES BTC_NOV10_DAILY_1M_ZIP FIVE_MINUTE_DIRECTORY [ADDITIONAL_FIVE_MINUTE_DIRECTORIES ...]` with the exact input receipts.
3. In the sandbox, run `fmz_round55_4052_fixture.py`. Then run `fmz_round55_4052_runner.py baseline` and `fmz_round55_4052_runner.py whole` beside `replay_2864.py` and `probe_1216.py`. Each native pass uses the full confirmed historical child data. Allow several minutes for the baseline pass.
4. Run `python -m research.fmz_round55_4052 SANDBOX OUTPUT_JSON` to validate against the independent arithmetic, documented fill rules and actual exchange evidence.
