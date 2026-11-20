# Strategy backtests round 6

The starting set is the 785 open catalogue IDs recorded in round 5. Every
one has fresh evidence in this round. The original `stratergies.xlsx`
adds 441 result rows for 83 newly tested strategies. Of those, 68 closed
at least one trade or lot and 15 did not. The audit records 198 source
exclusions and leaves 504 IDs pending with their evidence and blockers.
Across the 6,184-entry catalogue, 5,435 are tested, 504 are pending, 228
are excluded, and 17 point to existing reports.

## Framework replays

- Hummingbot IDs 5988 and 5989 use their archived spread settings and
  position barriers. The replay is limited to passive entry and target
  orders with a later opposing print strictly through the order price.
  Displayed bid or ask depth supports market exits after a stop or 45-minute
  timer. The timer starts at order creation. The dynamic controller
  recomputes its NATR and MACD from the preceding 142 completed three-minute
  bars. The replay uses conservative venue costs and normalizes leverage.
  [PMM receipts](nonpine-round6-pmm.json)
- Hummingbot ID 5969 retains the source's 1% net threshold. The BTC and ETH
  variant uses pre-funded balances, same-quote spot markets and synchronized
  snapshots from Binance, Bybit and OKX. It needs displayed size on both
  legs and tests the two-leg price after a one-second delay. The recorded
  sample had zero qualifying signals. [Cross-venue receipts](nonpine-round6-arbitrage.json)
- The Hummingbot timed order example, ID 5971, keeps the archived strict
  delay of more than 10 seconds and full position close. A 100 USDT
  configured stake clears the relevant minimum lot requirements and
  allows four historical BTC and ETH order-lifecycle tests. Standalone
  monitor, evaluator, and entry-only examples carry separate dispositions.
  [Framework source audit](nonpine-round6-framework.json)
- OctoBot ID 6009 retains a daily rebalance check, a five-percentage-point
  target drift threshold, and sell-before-buy sequencing. The configured
  basket contains 50% BTC and 50% ETH. The result counts closed asset lots
  and records the final two holdings as open. [Index receipts](nonpine-round6-index.json)
- OctoBot ID 6006 models the weekly DCA schedule, 5% resting-entry discount
  and source-configurable five-percent target and ten-percent stop. The
  time scheduler is replayed externally because the archived native mode
  disables it in backtests. Orders become eligible after placement and
  stops have priority when two barriers can be crossed within a minute.
  [DCA receipts](nonpine-round6-dca.json)
- OctoBot ID 6003 compares one-second snapshots of Binance last trades
  against the average of synchronized Bybit and OKX last trades. Neither
  direction reached the archived 0.25% entry threshold. Accordingly,
  the limit-entry and linked-exit rules did not activate during the fixed
  sample. [OctoBot arbitrage receipts](nonpine-round6-octobot-arb.json)
- Zenbot ID 5889 runs the pinned neural callbacks and ConvNetJS package
  with a fixed seed, 2,001 warm-up candles and 16 scored 30-minute candles
  for each of BTC and ETH. The worker runs in an AppContainer with Node
  file permissions. The history and callbacks run in the same JavaScript
  realm to finish the archived training loop in a bounded replay. The
  result uses the archived buy/sell advice with next-open spot fills.
  Each asset entered one position and ended the sample without a close.
  [Zenbot receipts](nonpine-round6-zenbot.json)

## Protocol replays

- Liquity Stability Pool offsets and redemptions use event-matched on-chain
  records, archived balances and size-specific swap quotes. The replay
  tracks observable protocol fees and modeled gas in the execution cost.
  Ribbon call and put vault cases use archived roll states and report the
  carry component. [Liquity and Ribbon receipts](nonpine-round6-vaults-redemption.json)
- Pendle YT carry, LP round trips and yield stripping use protocol receipts
  and verified market state. The basis keeps directional collateral returns
  outside the carry comparison. The LP study excludes incentive rewards.
  [Pendle receipts](nonpine-round6-pendle-carry.json)
- Deribit Jelly Roll uses the archived BTC inverse option quotes for all
  four legs, the exchange's 0.1 BTC increment and sufficient contemporaneous
  coverage to simulate entry and exit. It is a non-atomic quote model.
  Simulated execution at each quote can differ from a historical fill.
  [Deribit receipts](nonpine-round6-jelly.json)

## Source compatibility

The FMZ work uses pinned archives, public BTC and ETH exchange data and
isolated historical replay. It records symbol mappings, omitted display
operations and other repairs where they affect interpretation. A source
without an executable strategy has a different disposition from a source
with missing history or unresolved logic. The workbook selects the tested
native minute-cadence result for ID 1098. Its closed-candle reconstruction
is retained as separate evidence. [Pine methods](fmz-round6-pine.md) · [Native methods](fmz-native-round6.md) · [Native source audit](fmz-native-round6-audit.json) · [Protocol source audit](nonpine-round6-protocol-audit.json)

The pending intrabar cases include Pine strategies that enable Bar
Magnifier. Round 6 verified that the pinned PineTS engine exposes the
setting and lacks verified lower-timeframe broker execution in this
replay. The subsequent engine probe uses Piner 0.13.0 and checks the
intrabar sequencing and fallback counters explicitly. Its results are
outside this workbook update. [TradingView strategy semantics](https://www.tradingview.com/pine-script-docs/concepts/strategies/) · [Piner execution semantics](https://github.com/heyphat/piner/blob/main/docs/pine-semantics.md#9-bar-magnifier-use_bar_magnifier)

## Interpretation

Win rates count closed trades or lots with positive P&L in the matching
column. Zero closes produce a blank win rate. Workbook drawdown measures
each engine's documented equity path. Raw sources, parameters, and execution
models differ across framework and protocol replay variants. A historical
model result does not qualify a strategy for live or demo execution.

Where the pinned source contains only an indicator, monitor, account utility,
or otherwise incomplete standalone example, its exclusion is a source
disposition. External inputs, missing history, unresolved code, or
unverified execution rules remain pending. The audit reports these groups
separately from verified backtests.

[Per-ID reconciliation](remaining-backtest-round6-coverage.json) · [Round 5](remaining-backtests-round5.md)
