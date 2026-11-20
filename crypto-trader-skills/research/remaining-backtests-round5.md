# Strategy backtests round 5

This round resumes the 891 pending IDs in the previous round's disposition. It
verifies 106 additional strategies and adds 620 result rows in the original
`stratergies.xlsx`. Of the newly tested strategies, 86 had at least one close
and 20 had none. The catalogue now contains 5,352 tested strategies, 785
pending, 30 excluded and 17 existing reports, for 6,184 entries. The per-ID
disposition records each selected report, each pending status reason, and
pinned FMZ document hashes where a previous blocker was retained.

## Replay evidence

- The compiler work uses source-specific Pine repairs, isolated execution, and
  an independent fixture for entry, close, sizing, costs, and funding. Some
  source assumptions, such as fixed history offsets, archived capital, and
  input defaults, are stated in the variant names. [Compiler method](fmz-round5-compile.md)
- Pine feeds and timing replays reconstruct relevant session, reference-feed,
  and chart calculations only where the available history and fixtures support
  them. The trade fills use BTCUSDT and ETHUSDT Binance USD-M 15-minute
  replay inputs. The report records adaptations where that chart interval
  differs from the archived strategy. [Feed receipts](fmz-round5-feeds.json)
- The native FMZ work tests original JS and Python in an offline runtime and
  verifies equivalent calculations for specific JavaScript recipes and
  MyLanguage formulas. The notes identify changes to execution, parameters,
  and timing in each variant. [Native method](fmz-native-round5.md)
- Boros IDs 6152–6154 use BTC and ETH order-book snapshots, raw size-confirmed
  best quotes and on-chain funding receipts on the front and next Binance
  maturities. Each independent daily trial opens at 01:00 UTC and checks the
  opposite quote at 23:00 UTC. The calculations distinguish locked-rate
  cashflows, floating settlements, representative fees and gas. At-entry spot
  rates convert collateral-denominated cashflows into USDT for comparability.
  Missing closing liquidity or settlement excludes the episode from realized
  P&L and adds to the unsettled count. ID 6153 uses independently archived
  Binance funding on an existing short perpetual. It measures the funding
  hedge and omits the existing short's directional P&L and base-position costs.
  For ID 6154, four ETH trials closed and zero BTC trials closed. [Boros receipts](nonpine-round5-boros.json) · [Historical archive](https://historical-data.boros.finance/) · [Settlement mechanics](https://docs.pendle.finance/boros-dev/Mechanics/Settlement) · [Published fees](https://docs.pendle.finance/boros-docs/boros-systems/fees)
- Hummingbot ID 5997 uses an inventory-funded spot PMM variant with original
  refresh and filled-order delay parameters, and configured symmetric spreads.
  It requires a later opposite aggressor print through the live limit with at
  least the order size. Only matched FIFO pairs contribute to realized P&L.
  The 1% spread produced no closes. The separate 0.15% cost-based scenario
  closed 35 lots, and each market-day row had negative net P&L. [PMM receipts](nonpine-round5-pmm.json) · [Hummingbot source](https://github.com/hummingbot/hummingbot/tree/3351adad0a09f6a57a202219d3e52fe794672421/hummingbot/strategy/pure_market_making) · [Dataset specification](https://docs.tardis.dev/downloadable-csv-files)
- Pendle ID 6147 uses five independently verified Ethereum mainnet market
  swaps for each of PT-LBTC and PT-wstETH. The model holds to maturity and
  assumes par redemption in the accounting asset. It uses observed purchase
  gas and estimated redemption gas. The USDT results measure carry at the
  entry reference price and omit directional BTC/ETH exposure. Both samples
  had positive gross carry and negative after-fee P&L. [Pendle receipts](nonpine-round5-pendle.json) · [PT mechanics](https://docs.pendle.finance/pendle-v2/Introduction)
- Zenbot ID 5888 runs the pinned Pivot, MACD, Fisher Transform and Momentum
  callbacks in an offline AppContainer. A realm-neutral array check preserves
  the original Pivot condition for harness-generated history. This variant
  uses 15-minute Binance spot and next-open fills, with signal state retained
  across the callbacks for each bar. [Zenbot receipts](nonpine-round5-zenbot.json)

## Reading the results

Win rate counts strictly positive outcomes among closed trades or lots. A
zero-close row has a blank win rate. Drawdown is the peak-to-trough decline
of the reported equity path as defined per engine. The workbook preserves
separate gross, after-fee and after-all-cost results. Modeled fees, timing,
funding, execution costs and capital differ by engine and variant. Read those
assumptions before comparing P&L or win rates across replay families.

The audit is scoped to the 891 starting IDs. It retains statuses for known
blockers including unavailable original inputs and historical execution state,
incomplete sources, broker dependencies and unresolved compiler semantics.
New reports record reviews or attempts for 290 IDs. The remaining 601 carry
forward their previous blockers and have no new measured result in this round.
Standalone chart indicators, unconfigured hosts, and data gaps remain listed
under their original IDs.

| Remaining blocker | IDs |
| --- | ---: |
| FMZ native runtime or broker inputs | 431 |
| FMZ historical feeds, chart timing or intrabar data | 193 |
| FMZ Pine compiler or compatibility | 59 |
| Framework inputs | 45 |
| Protocol history and rules | 32 |
| FMZ source or data | 19 |
| FMZ implicit strategy configuration | 4 |
| Zenbot original learning runtime | 1 |
| Deribit Jelly Roll execution history | 1 |
| Total | 785 |

Coverage status is separate from live strategy qualification. The analysis
uses historical data while the Delta Demo entry hold is in place.

[Per-ID disposition and reconciliation](remaining-backtest-round5-coverage.json) · [Prior round](remaining-backtests-round4.md)
