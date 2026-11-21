# FMZ #4868 Cboe VIX and hybrid seasonal replay

The archive applies a long-only S&P 500 seasonal rule to a Binance BTCUSDT hourly chart in December 2023. The replay keeps the source's VIX, ATR and volume-flow rules, 100,000 USD account, 10% equity order sizing and 0.01% commission per side. ETHUSDT is a same-window comparison. Each market uses 744 official hourly candles with complete and matching 2,976 quarter-hour children. [FMZ strategy and saved market configuration](https://www.fmz.com/strategy/439619)

| Market | Closed trades | After-fee win rate | Gross P&L | After-fee P&L | After-fee drawdown | Positions left open |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 1 | 100.00% | 650.61 | 648.55 | 0.00 | 1 |
| ETHUSDT | 1 | 100.00% | 399.05 | 397.01 | 0.00 | 1 |
| Pooled closed-trade sequence | 2 | 100.00% | 1,049.66 | 1,045.56 | 0.00 | 2 |

Amounts are in USD. Drawdown uses realized closed-trade P&L and does not measure intratrade drawdown. Coinbase's preceding completed UTC day close supplies the USDT-to-USD conversion. Net marked P&L for the remaining BTC position is 243.98 USD and for ETH is 298.68 USD after the entry fee. Those marks remain outside the closed-trade table. This two-trade result has no ranking value. Funding, spread, slippage and live FMZ fills are outside the benchmark. [Coinbase Exchange candle definitions](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)

The source's unqualified `VIX` input resolves to the official Cboe daily close. The causal transport carries the previous close until the first hourly close after 16:15 New York time, or 21:15 UTC in this December interval. It forward-fills holidays and weekends. The generic daily merge disagrees with that clock on 40 raw observations and 47 rolling volatility ratios. The transport difference leaves the native literal execution signals and ledger unchanged. Independent formulas match each causal VIX, ATR and volume-flow value. [Cboe historical VIX data](https://www.cboe.com/tradable_products/vix/vix_historical_data/) [Cboe 2023 calculation and dissemination method](https://res-certification.cboe.com/api/global/us_indices/governance/Volatility_Index_Methodology_Cboe_Volatility_Index.pdf)

The pinned runtime's literal route ignores `ta.cross(i_critVFI, VFI)` when the scalar threshold comes first. The eight-bar negative control returns zero crosses for the scalar-first call and four crosses for both the swapped operands and explicit crossing formula. The independent historical series confirms two BTC money-flow crosses and one ETH cross. Swapping the operands and expanding the symmetric crossing rule independently produce the same order and equity ledgers. The workbook rows use that symmetric calculation. The literal route remains documented as a diagnostic with zero closed trades. [Pine v5 pattern and crossing API](https://www.tradingview.com/pine-script-reference/v5/#fun_ta.cross)

The independent ledger checks all six market fills against the opening price of both the native hourly and first quarter-hour bar. It reconstructs next-open percent-equity sizing, round-down lot handling, each converted fee and the hourly USD account. The first two settled fills close BTC at 41,225.10 USDT and ETH at 2,174.68 USDT. [Binance official public data](https://github.com/binance/binance-public-data)

## Reproduction

1. Pin catalogue commit `7853bb2bf262c4567ac238d3552d97f0e50cb801`. Stage the saved document as `source-4868.md` and the existing offline Pine runtime in the Windows AppContainer. The JSON report records the exact source and runtime digests.
2. Run `python -m research.fmz_round52_4868_stage HOURLY_ARCHIVES QUARTER_HOURLY_ARCHIVES VIX_CSV COINBASE_FX_JSON SANDBOX/4868-feed.json` with the archived input receipts. The Cboe download is a snapshot pinned in the report because the public file continues to append sessions.
3. Run `fmz_round52_4868_runner.py` in the AppContainer beside `replay_2864.py` and `probe_1216.py`. It produces the literal, whitespace control, release-timed transport, swapped crossing, explicit crossing and isolated crossing fixture.
4. Run `python -m research.fmz_round52_4868 SANDBOX OUTPUT_JSON` to verify traces, rates, marks and results. The published rows and the independent diagnostics are in `fmz-round52-4868.json`.
