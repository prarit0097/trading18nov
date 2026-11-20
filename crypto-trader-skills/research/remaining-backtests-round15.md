# Remaining strategy backtests · Round 15

Seven new strategy IDs added 32 workbook rows. Six produced closed trades or settled exposure cycles. One verified historical quote replay found no trade. The original 785-ID queue has 366 pending and 419 resolved. The full catalogue has 5,516 tested entries.

## Historical results

- FMZ #965 and #5474 executed on the authored daily charts with independent 30-minute Binance and hourly Bitfinex reference histories. Both backends and separate fill calculations agreed on 878 closures. The Bitfinex report records missing native hours and two ETH volume discrepancies. All daily OHLC values independently match, and its signal uses close prices. [Lower-timeframe replay evidence](fmz-round15-pine-lower.json)
- FMZ #3604 moves the archived fixed 50,000 capital value to the modern Pine declaration. Independent tests validate literal profit thresholds, same-open order precedence and fill prices. Four isolated runs closed 84 positions. The report includes a separate fee sensitivity charged at 0.075% per side. [Broker and capital controls](fmz-round15-3604.md)
- FMZ #171 preserves the two-hour source rules and uses DefiLlama daily circulating USDT as an explicitly labeled input variant. Each day becomes eligible at the next UTC boundary. Twelve closed lots across four replays were independently reconciled. Exact Glassnode equivalence remains unverified. [Supply replay](fmz-round15-supply.json) · [DefiLlama API documentation](https://api-docs.defillama.com/)
- FMZ #4978 reports three complete isolated BTC and ETH spot scopes. Every measured result reconciles to its native cash, holdings and atomic fills. The fourth scope stopped on the authored order-failure branch. Its abort evidence is preserved in the report. FMZ #1847 remains pending after its four source aborts. [Spot scope evidence](fmz-native-legacy-spot-round15.json)
- FMZ #5687 produced 1,784 independently matched ETH fills and no BTC fills. The report measures realized performance by observed flat-to-flat exposure episode. One mixed observation contains both a buy and a sell, so no transient within-observation position closure was inferred. [Spot cycle evidence](fmz-native-v001-round16.json)
- Polymarket #6178 checks both captured outcomes at all 300 seconds of one resolved BTC market. The cheapest complete-set ask was $1.01 and the highest complete-set bid was $0.99. No pre-fee edge qualified. The report identifies where paired quotes were absent and preserves the dataset revision. [Quote replay](nonpine-round15-complete-sets.json) · [Captured order books](https://huggingface.co/datasets/polyorderbooks/polymarket-btc-5min-historical-l2) · [Position mechanics](https://docs.polymarket.com/trading/positions/manage)

## Verification

The repository suite passed 340 tests and 89 subtests. The workbook retains win rate, P&L before fees, P&L after fees and modeled costs, and realized drawdown. Verification reconciles every new row, all 373 carried-forward candidate statuses and the complete result table range. Delta Demo remains paused. [Per-strategy audit](remaining-backtest-round15-coverage.json)
