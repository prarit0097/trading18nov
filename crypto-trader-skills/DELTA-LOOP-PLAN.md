# Delta demo trading loop

## Campaign goal

Build and operate a resumable Delta `india_testnet` crypto demo workflow
using `crypto-trader-skills`. Complete 10,000 demo trades of 10 contracts
each, targeting four concurrent entry lots across four distinct
crypto coins per batch. Rank operational perpetuals by USD traded turnover
among cohorts that pass margin, spread, quote freshness and risk checks.
Record every trade,
its fees, funding and realized P&L in `trade.xlsx`. Keep each lot's planned
loss at or below $10 including fees, the $30 daily loss limit, all
user-confirmed portfolio limits and the 10% five-hour Codex quota reserve.
Record WAIT as an entry-time observation and allow it in batch selection.

After every ten finalized trades, run a manager-led improvement cycle for
`crypto-trader-skills`. The manager delegates parallel analysis to
sub-agents covering execution, risk and costs, and strategy research. The
team reviews observed win rate, net expectancy and drawdown after fees and
funding, then proposes and tests concrete skill improvements aimed at
increasing the likelihood of profitable trades and improving net results.
The manager records the evidence, proposed changes, validation outcomes
and promotion decision for each review. Promote a version only when it
meets predefined criteria on independent subsequent data under the same
risk limits. Otherwise retain the current version. Report uncertainty
and avoid claiming guaranteed profits or unsupported strategy qualification.

## Updated operating rules

The owner's latest instructions replace the one-position and ready-signal
entry rules below. Plan four simultaneous demo entry lots of ten contracts
per batch across four distinct high-turnover crypto coins. Tokenized
commodities and equity-linked contracts cannot count. If fewer than four
eligible coins are available, skip the entire batch. WAIT is an entry-time research label. Keep the $10 per-lot
planned risk limit, the $30 daily cap and the 10,000 completed-lot target.
Do not start the next batch while previous entries or exits are unresolved.

Use a manager and two parallel reviewers when there is independent work:
one for execution, protection and accounting, and one for research and
validation. The manager combines evidence and proposes skill improvements.
The root agent owns integration, verified execution and promotion decisions.
Persist the manager's decisions in the campaign checkpoint.

- Journal all four individual order intents before transmission. Keep a shared
  product position identifier for entries on the same contract.
- Delta's product-scoped batch endpoint does not guarantee ten fills across
  products. Verify partial fills and coverage. Confirm that the supported
  entry path updates the exchange-side bracket for a netted position
  before enabling repeated same-product entries.
- Attribute exits to lots in FIFO order. Match aggregate funding, fees,
  proceeds and wallet cashflows first. Use the full USD balance chain for
  completeness when multiple products post transactions in the same window.
- Review every ten finalized lots. Capture batch ID, position episode,
  allocation reason and the observed WAIT/READY label before sending.
  Qualify changes on later non-overlapping batches. Shared exits and
  simultaneous lots must be clustered in inference. Test candidate
  ranking policies under the same four-entry and budget constraints.

Stops are not a guaranteed loss cap. Never reload the wallet automatically.

## Design

Use a local Python worker, the official pinned Delta MCP, shared JSON and
an Excel projection. A chat-only loop cannot survive app/host shutdown.
Retain exchange-hosted reduce-only protective orders. Start by importing
the existing manual BTC trade, without submitting it again. Keep manual
execution tests separate from strategy statistics.

Exchange fills and wallet transactions are authoritative for realized net
P&L, including actual commission/GST and funding. Unrealized P&L never
counts as a completed trade. Missing pages or unsettled cashflows block
finalization. Persist an order intent before sending; ambiguous responses
require reconciliation, never an automatic duplicate submission. Single
writer lock, fresh quotes, contract metadata, margin and protection checks
must precede autonomous execution. No production endpoint or credentials.

Review every 10 finalized trades: wins/losses/breakevens, net expectancy,
profit factor, drawdown, costs, Wilson interval and version attribution.
Ten outcomes are diagnostic evidence, not proof of future probability.
Freeze candidates before forward validation; do not optimize against the
same ten outcomes or auto-promote the historically rejected pilot.

## Implementation tasks

- [ ] 1. Read-only exchange reconciliation, trade JSON, batch review tests,
  and a verified trade.xlsx with the existing trade.
- [ ] 2. Tested testnet executor: account-wide single position, stale-data
  rejection, ten-contract risk, fee/funding reserve, margin, idempotency,
  partial fills, protection verification and fail-closed recovery.
- [ ] 3. Resumable worker with stop file, daily realized plus reserved loss
  gate in IST, maximum count, liveness and bounded supervised verification.
- [ ] 4. Ten-trade research queue and versioned candidate validation.
  No unsupported futures backtest or automatic strategy promotion.

At the owner quota reserve (10% remaining), save progress and stop starting
work. Do not leave an unverified order-producing worker running.

### Owner-confirmed active wait

An open protected position, pending settlement, or temporary lack of an
eligible four-coin basket is an active wait while the Delta Demo worker
is live and reconciling. Confirm the process and a fresh successful
cycle. Keep the Codex goal active during this wait when resumed.
After XRPUSD order 2178739530 reconciles, report its realized USD P&L
after commissions and funding. The worker submits the next four
distinct high-turnover coins at ten contracts each only after fresh
combined margin and risk approval. Every ten finalized trades, process
the existing manager and parallel agent review and validate candidates
on separate evidence before promotion.
