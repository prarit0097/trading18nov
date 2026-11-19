# Delta demo campaign checkpoint — 18 November 2026 IST

Goal remains incomplete: 10,000 completed demo trades, ten contracts each,
$10 planned risk including fees, one open position, $30 daily loss pause,
valid signals only. Owner approved these limits. No new orders were placed
during this implementation turn. Existing BTC order 2178653579 remains open.

Completed:
- Read-only official MCP reconciliation for the original BTC demo test;
  full pagination, explicit testnet environment, saved source responses.
- trade.xlsx: requested position, entry, leverage, SL, TP, fee-inclusive
  planned risk, order ID, fees, floating and final P&L columns.
- Summary formulas tested by temporarily changing a row to closed/-$4,
  checking updated count/net, restoring the source, and recalculating.
- Ten-closed-trade research queue: durable evidence hashes, version slices,
  win/loss/breakeven statistics and approximate Wilson uncertainty. Manual
  execution tests excluded from strategy win rate. No automatic promotion.
- Pure ten-contract risk planner: metadata units, finite numbers, raw fee
  validation, freshness, spread, funding reserve, daily reserved loss,
  existing-position and available-margin checks. It does not place orders.
- Read-only observer ran two live cycles without errors, then stopped.
- 125 unit/integration tests passed; compileall passed. Workbook exported,
  formula error scan clear, all sheets visually checked.

Changed implementation: crypto_skills/delta_ledger.py, delta_plan.py,
delta_observer.py; tests/test_delta_ledger.py, test_delta_plan.py; README.md;
DELTA-LOOP-PLAN.md; workbook builder and workbook under outputs/thread ID.

Latest saved account snapshot: 18 November 03:00:33 IST, BTC gross floating
P&L +$6.415; zero completed trades. This is a snapshot, not current-price
assurance. No local background observer or order-producing worker is running.
Existing SL/TP were exchange-hosted and verified when the trade was entered.

Remaining, in order:
1. Generalize importer from original manual BTC trade to multiple owned
   position lifecycles and symbols. Add account-import fixtures for partial
   fills, outside activity, pagination, preserved history and late funding.
   Existing importer explicitly flags conflicting BTC activity. Funding net
   remains provisional until a reliable completeness watermark is built.
2. Test demo executor idempotency/recovery, protection, partial fills, exchange
   rejection and liquidation/margin handling. Never submit on a stale state
   or ambiguous prior intent. Do not reuse spot risk approval as futures
   approval. Select only valid closed-bar signals as forward demo research.
3. Account-wide daily risk in IST, stop file, liveness, fee/funding reserve
   and holding-period rules; bounded supervised test before persistent mode.
4. Connect ten-trade queue to frozen candidate research/forward validation.
   Historical spot pilot was rejected; ten outcomes cannot prove improvement.
5. Operate and reconcile toward 10,000 actual closed demo trades. No target
   completion date promised; valid signals and exits take market time.

Quota rule: preserve 10% of the rolling five-hour allowance. Re-read live
usage before continuation; do not start work at >=90% consumed. Goal stays
active/incomplete; never mark achieved just because the reserve was reached.

Stop condition reached: latest verified five-hour reading is 90% consumed,
10% remaining. Work stopped under the owner's reserve instruction. All test
and observer processes finished; no delegated agent remains working.

## Owner resume instruction

### Six-coin batch — 18 November, 22:02 IST

- Owner requested exactly six distinct high-volume crypto coins, ten
  contracts each, and unchanged limits. The planner now checks aggregate
  margin across allowed 1x/2x/5x combinations before sending any lot.
  Keep manager and parallel agent skill reviews after ten finalized trades.
- Live preflight found six individually eligible instruments, but their
  minimum aggregate reserve was $183.14929180 even at 5x for all six,
  versus the permitted $130.050982056. No new order was sent.
- All 164 tests passed. Eight-coin session 96686 exited via STOP.
  Six-coin session **83082**, PID **11960**, completed a fresh cycle and
  exported Excel at 22:02 IST, with 2/10,000 closed and zero open. It
  watches for a complete eligible six-coin basket.

### Eight-coin batch — 18 November, 21:59 IST

- Owner reduced batch minimum to eight distinct high-turnover crypto
  coins with ten contracts each. The planner targets exactly eight
  distinct symbols. The per-trade and daily limits and manager-led review
  after every ten finalized trades still apply.
- Live preflight found eight listed crypto coins but only six passed
  checks. SOL lacked margin for ten contracts at the existing 5x leverage
  ceiling; DOGS exceeded the spread limit. An eight-coin batch cannot
  currently be sent. All 164 tests passed.
- Replaced the old worker after verified exit. New session **96686**,
  PID **19168**, completed an account and workbook refresh at 21:59:44
  IST with 2/10,000 closed trades, no open positions and zero new orders.
- User-authorized host goal resume was attempted through the app server
  and refused because this chat already had an active writer. The host
  goal remained blocked on read-back. Local worker is independently live.

### Nine distinct crypto coins — 18 November, 21:51 IST

- Owner now requires at least nine distinct crypto coins with ten
  contracts per entry in the same batch. Rank otherwise eligible
  products by USD traded turnover. Keep ten lots as the batch target.
  Repeated symbols cannot satisfy the nine-coin minimum. Tokenized gold,
  silver, oil and equity contracts do not count.
- Added the distinct-coin gate to the planner and before execution.
  Market turnover is journaled, exported and available in review
  evidence. Future markets must belong to the approved crypto universe
  and pass live product, quote, spread, margin and risk checks.
- Live Delta India testnet listed eight crypto-coin perpetuals:
  BTC, ETH, SOL, XRP, ADA, DOGE, 1000SHIB and DOGS. The live preflight
  blocked new orders before other gates. All 164 tests passed.
- ADA's previous ten-contract lot settled at net -$0.01514400. Verified
  campaign count 2/10,000. Updated observer session **31488**, PID **6268**,
  was live at 21:51:22 IST and exported Excel successfully. It submitted
  no orders and records insufficient_distinct_coins until coverage meets
  the updated requirement. The five-hour quota view remains unavailable.

### Manager review receipt — 18 November, 21:35 IST

- Use `python -m crypto_skills.delta_ledger --record-manager-review REPORT.json`
  after the manager and reviewers return. The report requires review_id,
  evidence_sha256, execution_findings, strategy_findings and recommendation.
  The receipt uses the reconciliation lock and refuses stale or unsettled
  evidence, preserving audited review history. It does not promote a policy.
- Full 161-test suite passed before adding the persistence regression;
  all 23 ledger and research tests passed with that final regression.
- Session 96506 was live. Latest observed cycle 19, one open ADA lot,
  one finalized trade and no workbook error. No manager review is due yet.

### Manager handoff for ten-trade reviews — 18 November, 21:33 IST

- Verified the owner's edited host objective and active status.
- Settled ten-trade reviews now queue a manager handoff in reviews.json
  with the exact trade evidence and a revision digest. Unchanged evidence
  does not requeue completed work. Corrected cashflows reopen the review
  and preserve the previous decision. The two work tracks are execution,
  risk and costs, and strategy research and validation.
- All 161 tests passed. No real manager handoff is due yet. On a future
  goal turn, inspect verified pending handoffs and use the manager and
  parallel sub-agents to review the evidence. The Python worker writes
  handoffs but does not start Codex agents itself.
- Existing session 96506 remained live. At 21:32:54 IST it had completed
  sixteen cycles with one open lot, one finalized trade and no Excel
  error. The new handoff code takes effect at the next worker restart.

### Durable batch attempt reporting — 18 November, 21:28 IST

- Observer now retains the latest actual batch attempt and its stop detail
  alongside the current cycle status. It persists the outcome before Excel
  export and carries it across restarts, so account-blocked hold cycles
  cannot erase a partial attempt's diagnostic. All 160 tests passed.
- Session 96506 remained live when polled, with eight successful cycles,
  clean workbook export, a protected ten-contract ADA lot, and campaign
  count 1/10,000. No new batch was submitted. The running worker will load
  the reporting update on restart; its exchange-hosted exits remain active.

### Stable ten-trade reviews — 18 November, 21:25 IST

- Reviews now keep their original ten filled order IDs when cashflows
  are revised or older trades settle late. Partial lots remain in the
  ledger and realized P&L, without advancing the ten-contract review
  count. A previously assigned review with unsettled data is flagged.
  The lot-level Wilson interval is omitted for shared batch exposures.
- All 159 tests passed. Session 96506 was still live after polling and
  four cycles had succeeded, with the open ADA lot protected and Excel
  current. Count remains 1/10,000. The running Python process will load
  the new review code on its next restart. No duplicate process started.

### First live worker-submitted batch fill — 18 November, 21:23 IST

- The observer now supports `--execute-batch-demo`. It verifies leverage,
  current inventory and shared brackets, checks the remaining margin reserve
  and refreshes per-symbol quote bounds before each IOC. Bulk quotes that
  are stale fall back to per-symbol reads. The workbook shows batch ID,
  requested, actual and remaining contracts, signal label and funding.
- Supervised batch `demo-1795017159238004000` filled one full ten-contract ADA
  lot, order **2178732870**, at 0.15068. Exchange SL 0.14947 and TP 0.15400
  covered all ten contracts. Nine slots were abandoned unsent. There are
  no unresolved submitted IDs. That version did not record the exact stop
  reason. The new version records per-attempt stop detail for diagnosis.
- 158 full-suite tests passed before the final stop-detail change; all 40
  targeted execution, ledger, planner and observer tests passed afterward.
  Live FIFO reconciliation and workbook export succeeded with the open ADA row.
- Continued batch observer **session 96506**, PID **5172**, verified live
  at 21:23:43 IST with one open lot, one completed trade, and valid Excel
  refresh. It waits for existing positions to settle before a new cohort.
  Poll this handle on continuation. Progress is 1/10,000; ten simultaneous
  fills and settled batch research remain unverified.

### Journaled demo batch submission

- The batch journal persists all slots and immutable entry metadata before
  sending. Each slot transitions to submitted_unknown before its IOC call.
  A timeout or uncertain state abandons remaining unsent slots, leaving the
  sent client ID available for read-only recovery. Filled lots carry the
  product episode ID and actual confirmed fill quantity into reconciliation.
- Reviewed Delta's India order guide with the parallel team. Position-linked
  brackets resize with the position. The first filled lot attaches a bracket.
  Later same-product lots reuse it and require verification at the new total
  quantity before continuing. Simulated undercoverage halts further sends.
- All 158 tests passed. The live read-only preview returned ten lots across
  four products, about $6.51 total planned risk and a quote expiration.
  Campaign count remains 1/10,000. No live order was sent this turn.
- Next wire live pre-send inventory and leverage checks and post-fill
  protection reads into the staged batch path. Only then replace the old
  worker mode. Keep STOP in place during implementation. The five-hour
  quota remains unavailable, with only the weekly window exposed.

### Batch accounting and research integration

- The parallel engineering and research implementations passed manager
  review. The ledger now reconciles a registered same-product group
  against the exchange position and wallet first, then assigns exits,
  fees and funding to individual lots. It refuses unknown entries and
  does not finalize individual lot P&L until the shared position is flat
  and the sum matches the wallet.
- The funding fallback now validates the full USD balance chain between
  fill-linked commissions. Other-product postings verify continuity
  without being attributed to this trade. Tests cover a missing posting.
- Completed ten-lot cohort reviews are saved under execution_cohorts with
  an entry-evidence fingerprint. The prospective selector excludes
  overlapping cohorts. Candidate ranking and promotion are pending.
- Live testnet preview still planned ten lots across four products for
  about $6.51 total planned risk. Existing count is 1/10,000.
- No batch order was transmitted. Next build durable batch submission
  and post-fill bracket verification. The batch path must populate
  position_episode_id, expected_filled_contracts, batch_id, batch_slot,
  entry_policy_version, entry_observed_at and signal_status_at_entry.

### Batch preflight and parallel team — 18 November, 21:06–21:10 IST

- Owner added a manager and parallel engineering/research reviewers.
  Reviews completed and the agreed work split and candidate qualification
  criteria are in DELTA-LOOP-PLAN.md. Host goal tools cannot edit existing
  objective text. The existing goal and progress were retained.
- Implemented and ran `delta_ledger --preview-batch` against the live demo
  venue. Ten 10-contract lots fit the saved $21.31993460 daily headroom:
  ADAUSD 6, XRPUSD 2, DOGEUSD 1, 1000SHIBUSD 1. The preview reserved
  $6.511798 planned loss and $125.794398 margin. Signals are recorded
  without vetoing WAIT. Quotes expire and require a fresh preflight.
- The STOP marker remains in place and no order was sent. Before execution,
  implement grouped order ownership, verify protection with repeated symbol
  fills, and reconcile aggregate position and cashflows to individual lots.
  Preserve the 1/10,000 completed count and BTC net loss of $8.68006540.

### Owner changed campaign entry rules — 18 November, 21:06 IST

- The owner wants ten demo trades open in the same batch and explicitly
  wants WAIT signals ignored. This overrides the prior one-position and
  ready-signal-only entry rules. Ten contracts, $10 planned risk per trade,
  the $30 daily loss limit and the ten-closed-trade review remain applicable.
- The previous worker (session 6130) exited normally via STOP. It placed
  no new orders. Keep the STOP marker until the batch path is ready.
- Live preflight reported $162.57887157 in demo cash. The confirmed
  realized loss of $8.68006540 leaves $21.31993460 for combined planned
  risk today. Testnet listed 17 live perpetuals, including non-crypto
  instruments. There were only seven qualifying crypto symbols in the
  initial spread and contract-unit screen. Ten independent crypto
  positions cannot be inferred from the thirteen qualifying products.
- Implement batch budgeting and ownership before sending entries. The
  exchange batches orders for one product at a time, and multiple same
  symbol fills can form one net position. If a ten-order batch needs
  repeated symbols, account for the individual lots and shared protection.
  Record WAIT at entry and retain it as data for subsequent reviews.

### Demo worker resumed — 18 November, 21:04 IST

- No prior worker or active lock remained. Restarted the local testnet
  worker on the same ledger. Exec session **6130**, observer PID **22232**.
  It completed two fresh account cycles and was live on re-poll. The gate
  was clear and the signal was waiting. Count 1/10,000.
- The workbook destination is held by another process, confirmed with
  an exclusive open probe. The worker records export failures and will
  retry while continuing to update the JSON ledger. The last good workbook
  already includes the finalized BTC trade. Do not terminate the holder.
- The expired five-hour percentage remains unavailable. The usage tool
  returned only the weekly window. The local demo worker uses no Codex
  model calls.

### First verified demo close — 18 November, 21:02 IST

- Fixed flat-position funding reconciliation. If the closing fill's funding
  field is zero while the wallet has posted funding, the fallback requires
  an unbroken wallet balance sequence from entry commission to closing
  commission, both linked to the respective fill IDs. Price P&L and fees
  still have to match. The regression covers a missing funding debit.
- The fresh read-only Delta cycle and Excel export passed. BTC's full
  ten-contract exit is finalized at net -$8.68006540, including both funding
  debits and commission. Campaign progress is 1/10,000, daily loss is
  $8.68006540, and the account gate is clear. Latest entry preview was waiting.
- No order worker was started. The usage tool continues to show only a
  weekly window, so the five-hour reserve remains unverified.

### Demo exit recovery — 18 November, 21:00 IST

- Confirmed observer lock owner PID 9212 was absent and archived the
  stale lock. A fresh read-only Delta cycle and Excel refresh passed.
- The BTC position exited all ten contracts at 63,188.50. Demo wallet
  evidence shows -$7.875 price P&L, $0.67524350 commissions and
  $0.12982190 funding debits, yielding -$8.68006540 from recorded cashflows.
  The closing fill reports zero remaining realized funding while both
  debits are present in the wallet. The current reconciler requires these
  values to match, so the trade is still pending and campaign count is 0.
- Next verify the funding field semantics, then update the reconciler
  and regression tests using the actual exit shape. The read-only cycle
  ended normally. No order worker was restarted. Five-hour quota is still
  unavailable from the usage tool, which shows only a weekly window.

### Recovery checkpoint — 18 November, 20:59 IST

- The usage tool now reports only a weekly window. The prior five-hour
  reading has expired, so no current five-hour percentage is verified.
- Session 89517 is missing and no matching worker process was found.
  The observer's running flag is stale. The last successful account
  snapshot was 19:15:53 IST after 157 cycles: zero completed trades,
  BTC still open with verified exits at that snapshot.
- The final recorded Excel export failed. The previous trade.xlsx is
  still present (19:15:18 IST). An observer lock remains on disk.
- Before restarting, verify the lock owner's PID, clear only a stale
  lock, reconcile the account and journal, and regenerate Excel from
  the latest authoritative ledger.

### Quota checkpoint — 18 November, 13:36 IST

- Live five-hour quota reached the owner's 10% reserve (90% consumed).
- Existing session 89517 remained live at the check. It had completed
  11 refresh cycles, with zero closed trades and no workbook error.
  Entry remained account-blocked. The existing worker was left running.
- Resume by checking quota, then poll the same worker session before
  considering any restart. Verify the first settled close and next
  worker-submitted eligible fill when available.

### Continuous demo worker — 18 November, 13:30 IST

- Started the testnet-only worker with `--execute-demo --until-stopped
  --poll-seconds 30`. Exec session **89517** was live after polling.
  Windows process inventory at startup showed uv PID 11100 and matching
  Python PIDs 19644 and 9212. On continuation, poll the same handle and
  check current process inventory before considering a restart.
- Two successful account-and-workbook cycles were verified by 13:30:34
  IST, with no account or workbook errors. BTC remained open with ten
  contracts, both exchange-hosted exits verified and floating gross P&L
  +$8.29. The entry result was `account_blocked`; campaign count 0/10,000.
- The worker can continue with the host running. A STOP file in
  `runs/delta-demo-loop` requests an orderly stop. Existing exchange
  protection stays in place. The first eligible worker-submitted order,
  real finalized cashflows and forward candidate results remain unverified.

### Worker recovery update — 18 November, 13:28 IST

- The observer accepts `--until-stopped` as an alternative to the bounded
  duration. Exchange call failures and transport timeouts retry from a
  fresh snapshot, with journal reconciliation before any new entry.
- Workbook export failure is tracked separately from account refresh.
  The exporter saves a temporary workbook and replaces the previous file
  only after successful export. STOP and the campaign target still end
  the run. Unconfirmed exchange protection remains a fatal stop for demo
  execution.
- At 13:28:41 IST the bounded demo run completed three successful cycles
  with workbook refresh and no errors. BTC was open with both exits
  verified and +$9.04 gross floating P&L; progress remained 0/10,000.
  The bounded worker exited normally. No new order was submitted.
- Full 144-test suite passed, and the additional observer integration
  test passed in the focused suite. It verifies timeout recovery, a
  failed workbook export, and orderly STOP in continuous mode.
- Next verify a real worker-submitted demo fill and closing-wallet
  accounting. The continuous mode has simulated recovery coverage;
  multi-hour live operation and real candidate outcomes remain unverified.

### Forward research update — 18 November, 13:25 IST

- The demo executor completed five supervised cycles over two minutes
  without errors, then ended. A subsequent one-cycle run refreshed the
  new workbook. Both reported `account_blocked` with one open BTC trade
  and campaign progress 0/10,000. No new order was sent.
- Every finalized batch of ten is reviewed. The first batch freezes the
  relative-volume >= 1.5 candidate, which is compared to the next 30
  fully filled, finalized baseline strategy trades with recorded signals.
  The journal stores signal evidence at submission. The screen measures
  net P&L, observed win rate and daily paired effects for a skip-only
  filter, without modeling replacement trades. It does not promote a rule.
- The Excel summary shows campaign progress, the next review threshold
  and validation status. Its totals cover every exported trade row.
- 142 tests passed, including freezing, excluding pre-freeze trades and a
  synthetic passing forward screen. The current account has no finalized
  review batch, so the live forward comparison is still awaiting data.
- Next verify first real demo close and first worker-submitted fill, extend
  continuous resume operation, and use independent validation to decide
  whether to promote any candidate that passes the forward screen.

### Supervised demo execution update — 18 November, 13:21 IST

- The bounded observer now accepts `--execute-demo` (implicit signal scan).
  It checks account inventory and today's fill ownership before changing
  leverage, reads leverage back, refreshes the risk plan and checks inventory
  again before journaled IOC submission. The stop file or an expired quote
  prevents transport. Filled entries trigger immediate account reconciliation.
- A live one-cycle run of that mode finished normally, refreshed trade.xlsx
  and reported `account_blocked`. BTC was still open, both exits were
  verified, gross floating P&L was +$7.36 and the count was 0/10,000.
  No new order was sent. The observer finished and is not running.
- 139 tests passed. The eligible submit branch passed with simulated tool
  responses. A new real demo fill through the worker remains unverified.
- Next, run bounded supervised cycles as the current position settles and
  verify actual order/fee/funding behavior. Add ongoing resume operation
  and completed-batch candidate validation before claiming campaign readiness.

### Signal and preflight update — 18 November, 13:18 IST

- Used the crypto-entry closed-candle rule for Delta BTCUSD, ETHUSD and
  SOLUSD. The five-minute scanner rejects missing, stale, duplicate and
  invalid candles in its signal window. Its 20-bar baseline version is
  recorded with each observation.
- `delta_ledger` and `delta_observer` accept `--scan-signals`. When the
  account is clear and a fresh signal is ready, the preview reads the USD
  wallet, contract metadata and current ticker, then runs the ten-contract
  risk planner. The saved proposal expires with its quote or signal.
- All 137 tests passed. Live scanner-to-ledger-to-Excel refresh passed.
  At 13:18:07 IST all three signals were waiting. The existing BTC position
  was open, SL/TP verified, gross floating P&L +$6.805, count 0/10,000.
- The preview currently performs exchange reads. Next connect execution to
  a refreshed account and leverage check, journaled IOC submission and
  post-fill reconciliation. Batch candidate validation remains pending.

### Order-recovery update — 18 November, 13:13 IST

- The host goal is active again. The five-hour quota at restart was 38% remaining.
- `crypto_skills/delta_execution.py` records an IOC entry intent before sending,
  prevents reusing a signal, and recovers an uncertain response by client order
  ID. Unresolved orders hold the campaign gate. Confirmed full and partial
  fills enter the existing reconciliation pipeline.
- Each refresh verifies the two exchange-hosted reduce-only exits against
  the remaining contract count, configured trigger levels and mark-price trigger.
- All 131 tests passed, including lost-response recovery, production rejection
  and partial-position protection checks. Live read-only Delta and Excel refresh
  completed and exited normally. At 13:13:25 IST, BTC had 10 contracts remaining,
  both exits verified and +$5.49 floating P&L. Campaign count was 0/10,000.
- The submit path has test-double coverage and is not wired into the observer.
  Next integrate fresh closed-bar signal selection, active-order leverage and
  account preflight, supervised testnet submission and post-fill handling.
  Independent candidate validation and long-running operation remain pending.

### Continuation update — 18 November, 12:59 IST

- Live quota recovered (94% remaining at restart). The existing host goal
  still reports `blocked`; the available goal controls cannot reactivate it.
  Implementation work resumed on the same objective and history.
- `delta_ledger.py` now reconciles registered orders by product and the
  exchange's position size after each fill. It handles partial exits,
  deduplicates fills, and assigns later entries to a new lifecycle. A
  closing fill's realized funding must match the wallet, along with gross
  exit proceeds less entry cost and posted commissions, before booking net P&L.
- `delta_plan.py` now exposes IST daily realized loss and the remaining
  planned risk budget. The gate sees account-wide positions and orders and
  caps campaign credit at fully filled ten-contract trades. The daily loss
  calculation currently covers reconciled campaign trades.
- 128 tests passed. A fresh Delta-to-Excel observer cycle ran successfully
  and exited normally. At 12:59:25 IST, BTC order 2178653579 was open with
  ten contracts and +$7.345 gross floating P&L. Both reduce-only exit
  orders were pending for all ten contracts. Count: 0/10,000.
- Next: verify funding and closing-wallet behavior on an actual demo exit,
  complete authenticated order intent/recovery and signal execution, then
  connect the review queue to independent candidate validation. The current
  BTC position occupies the one permitted position slot.

Owner requests that a later "continue" resume this same full campaign and
its learning workflow. Preserve the original 10,000-completed-trade objective;
do not create a different goal or reset performance history. The latest
verified quota reading after the stop was 91% consumed / 9% remaining.

On continuation:
1. Read live five-hour quota. Resume work only above the 10% reserve, unless
   the owner explicitly changes that reserve. Unknown quota is not approval
   to assume a reset. Report the visibility limitation.
2. Read this checkpoint, DELTA-LOOP-PLAN.md and current goal status. Resume
   the existing goal using the host's supported goal-resume mechanism when
   available; do not mark it complete or claim it is active without evidence.
3. Reconcile current india_testnet connection, all account positions,
   orders, fills and wallet cashflows before making a trading decision.
   Do not assume the previously open BTC trade is still open. Preserve
   external or unresolved activity as a reconciliation issue.
4. Inspect actual process handles and leases before starting any worker.
   Never start a duplicate worker or resend an ambiguous order intent.
5. Complete remaining executor, lifecycle accounting, funding completeness
   and recovery tests before enabling automatic entries. Current code only
   performs read-only refresh and risk arithmetic; it cannot yet run the
   full autonomous campaign. After verified readiness, resume the loop from
   its persisted count and budgets, rather than restarting at trade one.
6. Refresh the existing trade.xlsx from the reconciled JSON ledger. Count
   finalized closed trades only. Review each newly completed ten-trade batch
   once using its persisted evidence ID; keep late P&L adjustments auditable.
7. Learning means versioned research: diagnose net expectancy, costs,
   drawdown and outcomes; freeze candidate changes; validate on separate
   historical/forward evidence with futures costs accounted for. Promote
   only candidates that pass predefined validation, retain rollback and
   version attribution, and keep manual tests out of strategy statistics.
   Never treat ten outcomes as proof of higher future win probability.
8. At the quota reserve, persist an updated checkpoint and stop new work.
   Report which processes are actually running and which protective orders
   were verified. Do not promise unattended operation or profit improvement.

### Active monitoring milestone

Keep the 10,000-trade Delta india_testnet objective. Monitor ETHUSD order
2178739526 and XRPUSD order 2178739530 through exchange reconciliation and
report each realized USD P&L after commissions and funding. Let their
existing exchange exits operate. The existing worker can submit the next
four distinct high-turnover coins at ten contracts each once reconciliation
clears and fresh combined margin and risk checks pass. Keep the existing
limits, ledger history and manager-led review every ten finalized trades.
The local campaign continues on the existing worker. The Codex goal still
reports blocked and its objective cannot be edited through the available
goal controls. The live five-hour quota window was unavailable.

- Worker restarted on the tested reconciliation fix. 164 tests passed.
  ETHUSD exited at $1,733.60 with $0.18503492 commission, zero funding and
  realized P&L of -$1.93003492. The restarted worker booked it in the
  ledger. XRPUSD remains open with its exchange stop and target verified.
  Campaign progress is three finalized trades. The next batch is gated
  on XRP settlement and a fresh combined preflight.

### Monitoring checkpoint — 18 November, 22:35 IST

The running Delta india_testnet worker (PID 26404) completed cycle 20.
XRPUSD order 2178739530 remains open for ten contracts with exchange
protection verified. Three trades are finalized and no manager review is
due. The next four-coin batch requires XRP to close and reconcile, then
fresh combined margin and risk approval. The live local worker continues
polling and the workbook remains the record. Repeated goal turns reached
the same exchange-state dependency. The five-hour quota was unavailable.

### Active-wait policy — 18 November

The owner confirmed that a healthy worker waiting for a protected trade
to settle does not require stopping the campaign or marking the goal
stalled. Keep monitoring the existing worker and process reviews when
due. The currently blocked Codex goal requires the app resume control.

### Setup for the revised goal — 18 November, 23:20 IST

Use the attached goal objective as the campaign specification. This
section supersedes the old five-hour quota and coin-selection notes.
The CEO coordinates one profitability manager and five specialists.
The worker runs under ENTRY_HOLD while the Codex goal is paused. Its
normal batch is four distinct BTC, SOL, ETH, DOGE or XRP USD perpetuals,
ten contracts per coin. If partial fills leave one to three trades at
the end, the final batch uses exactly that many eligible coins. The
campaign tally includes eligible, finalized ten-contract trades. Older
ADA history stays in the ledger and daily risk calculation.

Resume only after confirming the user's goal is active, the existing
worker is live and reconciled, and verified weekly Codex quota remaining
is above 50%. Release runs/delta-demo-loop/ENTRY_HOLD then observe the
existing worker rather than launching another. It queries Codex before
entry and holds for a missing, stale or at-reserve reading. Check live
weekly quota during goal turns and finish minimal checkpoint work at
the reserve. While XRP is open and protected, keep the goal active and
wait for settlement. Report net XRP P&L when the closing fill, fees and
funding reconcile. The worker applies the same active wait to ordinary
temporary budget and eligibility conditions.

When the ledger exposes awaiting_manager review IDs, read the matching
campaign_reviews.manager_handoffs evidence in reviews.json. The CEO
coordinates the manager and all five specialties, running the reviews
in waves if agent slots are limited. Submit the findings and decision
using python -m crypto_skills.delta_ledger --record-manager-review REPORT.json.
Use the exact review_id and evidence_sha256, the five specialists keys
market_data, entry_exit, risk_costs, execution, reconciliation_validation,
manager findings and recommendation, and CEO decision and rationale.
Use retain_current or test_candidate. For test_candidate, include the
candidate version, baseline_version, hypothesis and validation_protocol.
The worker waits on due reviews before starting another batch. Do the
final review even if the worker has already reached its trade target.
Only promote after independently verified results under the same limits.
The code persists the review and frozen candidate. The Codex team
performs the qualitative analysis, tests candidates and decides promotion.

Verified during setup: 173 unit tests passed. The new worker reconciled
XRP with both protective exits, reported entry_hold, and refreshed
trade.xlsx. Two trades qualify toward the new count. No review is due.
The live weekly reading was 97% remaining. The goal was left paused.

### Reconciliation scaling — 18 November, 23:28 IST

The interpreter now indexes fills and wallet timestamps once per
snapshot. All 173 tests passed, and replay of the current Delta data
preserved each trade's status and P&L. Local CPU reconciliation took
0.596 seconds for 10,000 synthetic settled trades. This benchmark does
not include Delta API pagination or workbook export. The live worker
continues monitoring protected XRP. The code change will take effect
on a controlled worker restart.

### Trade 1 history refresh — 19 November, 03:25 IST

The Trade 1 observer reads fills and wallet postings from the first registered entry on each cycle, before checking timed exits. Five read-only Delta India testnet calls per endpoint measured a median of 0.360 seconds for a 50-fill page and 0.216 seconds for a 100-row wallet response requested at page size 200. The budget for a complete observer snapshot is 55 seconds. At two fills and three wallet postings per trade, 10,000 trades would require roughly 400 fill pages and at least 150 wallet pages. At the observed medians those sequential reads alone would take about 176 seconds. This projection excludes later repeats, partial executions, larger payloads and other observer calls.

Keep current inventory and fills used for the exit and daily-risk checks fresh. Move older fully paginated evidence outside that time-critical path, retain raw identifiers and revision history, and audit late wallet corrections before finalizing the campaign. Verify recovered and incremental results against a full historical reconciliation before changing the worker's history path.

Exact-microsecond read probes found both history endpoints exclude an event at `start_time_us` and include it at `end_time_us`. Trade 1 requests one microsecond before an inclusive start. After the 40th verified trade settled, the observer restarted with this change. At 03:45:02 IST it reconciled all 40 closes and the same net P&L of −$5.64085485 with zero open exposure and review 4 due. [Ledger source](crypto_skills/delta_ledger.py)

The 03:35 IST test divided the same history into five consecutive windows ending at one fixed cutoff. Using 25-row pages and comparing the full returned records by fill ID and wallet UUID, the windowed read matched all 76 fills and 112 wallet postings with zero duplicates. It used five fill pages and seven wallet pages versus four and five pages for the full read. Window partitioning preserves the sample when every cursor is exhausted. The performance benefit requires reusing completed windows and keeping a separate audit for revised historical records.

Before using archived windows in the observer, bind the archive to the testnet account, request filters and exact interval. Keep the day-risk data and the earliest unsettled entry in the fresh read. Publish only exhausted windows and replace a revised window atomically with its audit record. Compare trade statuses, money totals and review evidence hashes against the full-history reader with identical cutoffs. Include restart after a truncated page, repeated cursors, boundary fills and late funding in the comparison.

The first implementation step pairs a complete cursor reader with immutable SQLite window revisions. Use `(start, end]` exchange bounds, validate source row identities and wallet ownership, and preserve prior payloads when a refresh changes them. Compare the archived result by record identity and content against an independent full testnet fetch. Worker integration requires a separate check of open exposure, live day-risk inputs and late historical corrections.

At 05:34 IST the archive core matched every field of 114 fills and 170 wallet postings across seven exact windows to an independent full Delta India testnet fetch. A reopened 60 KiB SQLite file served the same rows with the exchange reader disabled. Unit tests also covered repeated cursors, wrong wallet accounts, exclusive start boundaries, late revisions and digest errors. The shared cursor reader now backs the observer source. The running worker still uses the full-history path, and production cache integration remains pending.

### Funding posted during closing settlement — 19 November, 05:43 IST

ETHUSD order `2178760912` and XRPUSD order `2178760919` closed on their timers after crossing 00:00 UTC. Delta posted each funding charge after the closing fill and before the cashflow and commission for that close. The wallet's uninterrupted USD balance chain and the fill ID on the closing commission verified the settlement. The ledger now checks this posting order and matches the cashflow's exit price and size to the fill before attributing funding to a closed single owned lot.

Replaying the live exchange rows preserved all prior 56 settlements and added the two closes at −$0.23438703 and −$0.01536972 net. Funding was −$0.00533154 and −$0.00029043 respectively. All 237 tests passed. After the controlled restart the observer verified 58 closes, −$7.27059637 cumulative net P&L and zero open or unresolved exposure before entries resumed. The observer continues reading full exchange history while its historical cache work is tested separately.

### Archived history combined with fresh exchange data — 19 November, 05:49 IST

The archive reader uses a complete, disjoint prefix and fetches the rest from Delta. It falls back to a full read if a window is missing, its digest fails, or a fresh record duplicates an archived ID. IST day partitioning leaves the exact midnight event in the fresh range. The live comparison used six historical hourly windows and a fresh tail at one fixed cutoff. All 120 fills and 180 wallet postings matched an independent full read. With a warmed archive, fill pages fell from six to one and wallet pages from nine to one. The initial backfill is outside those page counts. This check ran alongside the worker and its execution path continued to use full history.

### Verified archive publication — 19 November, 06:08 IST

The Trade 1 ledger source can now read an account-bound archive and fetch today's history and the oldest pending settlement's entire IST day from Delta. Unknown order ownership, an absent or mismatched archive, or an incomplete historical prefix falls back to the full exchange read. Live positions, open orders and the entry-time inventory checks still query Delta directly.

`uv run --no-project --with mcp python -m crypto_skills.delta_ledger --campaign trade1 --refresh-history-archive` builds past-day windows separately from the observer. It publishes only after every row matches a separate complete exchange read over the same range. A failed comparison leaves the existing archive and its revisions available. Refresh eligible days again to detect backdated wallet corrections, and verify the final campaign with a full exchange read.

The archive refresh command found zero eligible prior IST days in the active campaign. A cloned run against the same testnet account used a simulated historical cutoff and published a verified archive with 104 fills and 155 wallet postings. The normal ledger snapshot then combined it with fresh Delta data. All 62 trade settlements, risk inputs, 124 fills and 188 wallet postings matched a full read. All 242 tests passed. The live worker was left on full history pending a real prior-day comparison.

### Batch execution evidence — 19 November, 06:22 IST

The first 28 staged batches had 112 planned lots. Sixty-six filled all three contracts, 12 submitted IOC orders filled zero, and 34 staged lots were never submitted. Ten batches filled all four lots. The exchange attributed all 12 zero fills to insufficient size at the order book limit. Five staged lots retained a direct quote failure, each with the ask above its saved IOC limit. Later slots in the same batch can inherit the effect of a guard that first failed on another coin. These counts do not measure what a larger limit would have achieved.

New journal writes record the reason when the worker abandons a staged lot. They distinguish a failed preflight, an ambiguous prior submission and a staged lot found on restart. The reason stays with the batch for future reviews. Older records cannot always recover that reason. All 242 Python tests passed. The active worker was not restarted while its four demo positions were open.

The production workbook builder exported a temporary synthetic sample of 10,000 verified-format trades, 1,000 reviews and 20,000 exit comparisons in 115.64 seconds on this machine. The resulting XLSX was 3,639,645 bytes. Its Overview counts and net P&L matched the independent input calculation, and all three table ranges reached their expected final rows. This fits the 300-second export timeout. The benchmark supplied synthetic rows separately and left the live workbook and trade count unchanged.

### Review 7 and worker diagnostics — 19 November, 06:41 IST

The batch opened at 06:28:33–06:28:39 IST closed all four three-contract positions on their timers. It recorded −$1.10879283 net, including $0.49829283 in fees and zero funding. The live ledger and workbook show 70 verified closes, −$10.63710471 in cumulative net P&L and six finalized reviews.

Review 7 covers trades 61–70 across three entry baskets. An independent India testnet read matched 20 fills, 20 fill-linked commissions and ten closing wallet cashflows. The ten trades had −$1.41450000 gross P&L, $1.23675514 in fees, zero funding and −$2.65125514 net. Nine orders came from WAIT signals and one from an unavailable signal. None had a READY signal. The final modeled 30-minute reference bar becomes eligible at 06:59 IST. The existing review gate holds new entries until the evidence-bound review is recorded.

The prior observer exited normally at the flat review gate, and the restarted observer has verified the same 70 settled trades. It now records batch stops, preflight bid and ask, available versus required margin, exchange quote time and local submission start alongside new intents. The 242-test suite passed. The ten-minute timer and frozen prospective strategy comparison remain in effect.

The five specialists and profitability manager completed their assessment of actual trades. At 06:44:22 IST the observer had finished the 15-minute comparison. Three entries were usable, seven lacked sufficient evidence, and neither the actual nor the modeled outcomes won in the matched set. The mean change was −$0.00795402 per matched entry. Eight 30-minute estimates remained pending and two were unavailable. The manager recommends retaining the 10-minute baseline and evaluating the frozen four-READY hypothesis on its prospective sample.

At 06:59:45 IST the CEO recorded review 7 against the terminal evidence digest. The 30-minute baseline comparison had three matches with zero wins before and after, seven unavailable, and a mean change of −$0.89328316 per matched entry. Across 70 closes, the 15-minute comparison matched 32 entries and averaged −$0.09110112 relative to actual exits. The 30-minute comparison matched 25 and averaged −$0.05754573, while recording eight modeled wins versus three actual. These shared and incomplete subsets support retaining the 10-minute rule pending independent evidence.

The deadline-depth probe captured contemporaneous public books for the last four positions' 30-minute deadlines. Three snapshots passed timestamp checks. XRP's trade candle had no volume, and its same-minute book covered all three contracts. The resulting extra modeled loss was −$0.02701210. This improved coverage in one basket from three estimates to four. The probe is recorded in `runs/trade1/review7-deadline-books.json` and is outside the original paired review statistics. The optional replay requires mark-bar coverage, fresh same-minute depth and sufficient full-size bids. All 243 tests passed.

### Post-deadline public depth capture — 19 November, 07:04 IST

Order 2178765494 for BTCUSD was sent for three contracts at a $62,639.50 IOC limit. The saved ask was $62,638.50. An independent India testnet order query confirmed cancellation for insufficient available book quantity and zero filled contracts. The saved ticker quote contained no size at the limit, and its exchange timestamp was about 5.26 seconds before order creation. The evidence cannot distinguish thin initial liquidity from a subsequent change. The ETH, XRP and SOL entries from this batch each filled three contracts, with protective orders verified.

`python -m crypto_skills.delta_shadow_capture --batch-id demo-1795051800781051100 --minutes 15` captures public depth for the exact first-fill deadlines of those three positions. Use `--minutes 30` for the second horizon. Separate invocations hold only their own capture locks and publish evidence under `runs/trade1/shadow-books-<batch>-<minutes>.json`. A missed deadline stays unavailable. Both captures started before the scheduled 07:15 and 07:30 IST windows. They are read-only market observations and do not write campaign trade, order, or review state. All 246 Python tests passed.

The three positions settled by 07:10:09 IST. Six fills and nine wallet postings reconciled to −$0.29854138 net, $0.29554138 in fees and zero funding. The workbook verified 73 campaign closes, −$10.93564609 cumulative net and seven finalized reviews. A later batch filled three BTC contracts and stopped further submissions when the ETH ask exceeded its saved limit. BTC's brackets were verified and its timed exit is due at 07:22:27 IST.

The 15-minute capture recorded valid books for all three earlier positions. Candle replay had two usable estimates. The displayed-depth fallback covered SOL's otherwise empty reference minute, for a modeled net result of +$0.23742489 using the recorded fees and slippage assumptions. The result and raw book are saved in the separate research artifact. The 30-minute capture was still live for its 07:30 IST window. Official review comparisons retain their registered method.

### Zero-gross XRP settlement — 19 November, 07:38 IST

The single BTC position from batch `demo-1795052546367178700` closed on its timer with −$0.45936019 net, including $0.19986019 in fees. Its 15-minute research estimate was −$0.16374350. The 30-minute depth capture for the earlier ETH, XRP and SOL batch returned valid books for all three coins. Funding after the intervening UTC hour was unverified for those hypothetical positions, so no 30-minute P&L was recorded.

All four positions from batch `demo-1795053165936084400` closed. XRP bought and sold exactly three contracts at $0.9615. An independent India testnet query verified the reduce-only close and an empty account inventory. Its wallet showed two fill-linked fees of $0.00153168 each and a continuous balance chain. Delta omitted the zero cashflow posting.

The reconciler now accepts that exact-zero gross case when both commissions and the wallet balance chain verify. The regression also checks nonzero gross, a broken balance chain and incorrect fee attribution. A read-only account replay preserved the earlier 77 trade outcomes and verified the XRP net of −$0.00306336. All 247 tests passed. The observer restarted after the exchange confirmed zero open positions and orders. The full batch then reconciled at +$0.13832744 net, including $0.49617256 in fees and zero funding. The campaign reached 78 verified closes and −$11.25667884 cumulative net.

The four-leg batch's 15-minute research used the captured XRP bid depth to cover an empty trade minute. XRP's modeled net was −$0.00750175. The official trade and review accounting uses the exchange fills and the registered comparison method.

### Reproducible depth evaluation — 19 November, 07:43 IST

Add `--evaluate` to the depth capture command to score an existing research artifact after its reference minute completes. The evaluator joins the exact batch, order ID, coin and first-fill deadline to a verified settlement before using public mark and trade candles. It retains the raw book and stores the candle and depth estimates beside actual P&L, in the separate research artifact. All 248 tests passed.

The BTC position opened at 07:12:27 IST had a valid captured book at its 30-minute deadline. The paired estimate was unavailable because the extended hold crossed a UTC funding boundary with no verified cashflow for that hypothetical position. No modeled P&L was credited.

### Trade 80 and review 8 — 19 November, 07:54 IST

ETH and XRP from the 07:38 batch settled at −$0.06707267 net with $0.05957267 in fees and zero funding. The observer and workbook both show 80 verified closes, 16 net winners, −$11.32375151 cumulative net and seven finalized reviews. The observer is live and flat at the eighth review gate.

Five specialists and the profitability manager examined trades 71–80. Independent India testnet reads matched 20 fills, 20 commission postings and nine cashflows, with the fee-only XRP close verified from the continuous wallet chain. Review 8 yielded +$0.36450000 gross, $1.05114680 in commissions, no funding, and −$0.68664680 net. Three positions won after costs. All ten entered on WAIT across four filled baskets. Eight staged attempts produced ten fills, three submitted zero fills and 19 legs abandoned before submission. The manager recommends retaining the 10-minute baseline and testing whether quote age and displayed depth predict after-cost performance across prospective day blocks.

The standard 15-minute comparison closed at seven matched trades, three unavailable and zero pending. Its modeled win count fell from three to one, with mean net change −$0.00558828 per match. Separate depth research recovered three empty trade minutes and provided a full ten-trade comparison. Its modeled net was −$0.34372949, with two winners against three actually observed. Those estimates are excluded from official comparison statistics. At 07:54 IST the standard 30-minute comparison had four matches, four unavailable from unverified additional funding, and two pending. The last reference candle completes at 08:09 IST. Submit the final review only against the refreshed digest when both comparison pending counts reach zero.

### Review 8 finalized and pre-window candle capture — 19 November, 08:11 IST

The CEO recorded review 8 at 08:09:51 IST. The standard 30-minute comparison finalized with five matches and five unavailable, three actual wins and zero modeled wins, and a mean change of −$0.19769532 per match. The depth probe added one 30-minute estimate and had zero wins across six. Across all 80 trades, the standard 15-minute and 30-minute paired estimates averaged −$0.07575266 and −$0.08090399 relative to actual respectively. Review 8 retained the 10-minute rule. The workbook verified eight complete reviews and −$11.32375151 net.

A pre-window 24-hour probe found all five required candle histories in 287 of 288 decision windows. At 08:00 IST the live 21-bar request omitted two leading zero-volume DOGE candles. At 08:05 the 24-bar request still left a gap. A 48-bar request provided enough preceding history in the 08:10 probe, where all five coins supplied their original 21-bar signal window and valid quotes within 5.323 seconds of the boundary. Only those 21 completed bars are used and retained for the breakout calculation. The regression and all 249 tests passed. Only the public decision recorder was restarted. Its database identity matched the frozen registration, with zero observations before the validation window.

The next Delta demo batch filled BTC, ETH and XRP at three contracts each. SOL had zero fills. The three open positions have verified protective orders, $4.4301396 combined planned risk and timer exits due at 08:20:06–08:20:10 IST. Public 15- and 30-minute depth captures for the batch are scheduled separately.

The 80-trade accounting check found 31 gross winners, 16 net winners, and 15 positive-gross trades that were flat or negative after costs. Total gross P&L was −$3.18900000, commissions $8.12912954, and signed funding −$0.00562197. Commissions were 10.6178 basis points of aggregate entry notional. Costs reduced returns in this sample, and the gross total was already negative. The ten verified trades with captured entry asks all filled at or below their recorded asks. Those snapshots are too sparse to establish execution costs at submission or opportunity-level performance, because the failed and unsent legs have different coverage.

### Trade 87 accounting — 19 November, 08:32 IST

BTC, ETH and XRP from batch `demo-1795056005312066600` settled at −$0.26183705 net with $0.25883705 in commissions and zero funding. All three 15-minute research books were valid. The candle comparison covered all three and modeled −$0.15586960 net, with zero winners at both horizons.

All four legs of batch `demo-1795056670127012500` then settled at −$0.56798554 net, $0.49448554 in commissions and zero funding. Two public ticker snapshots spanning 03:00 UTC returned a rate field but no next-realization timestamp for any of those four symbols. REST ticker snapshots therefore do not establish the hypothetical funding schedule. The actual zero funding followed from wallet reconciliation.

The observer and workbook show 87 verified closes, eight finalized reviews and −$12.15357410 cumulative net. The next batch `demo-1795057294505560000` filled three BTC contracts. ETH's quote guard stopped the later submissions. BTC's protective orders are verified and its timed exit is due at 08:41:35 IST.

### Trade 88 and replay execution counts — 19 November, 08:42 IST

The single BTC timer close settled at −$0.47528910 net, with $0.19928910 in fees and zero funding. The next batch `demo-1795057912436378200` filled all four planned coins at three contracts each and the observer verified all protective orders. Its combined planned risk was $7.5908300, with timer exits due at 08:51:53–08:51:59 IST.

The 15-minute research comparison of the preceding full batch `demo-1795056670127012500` used four matches and modeled −$1.18125947 net versus −$0.56798554 actual, with no winners at either horizon. The prior BTC, ETH and XRP batch returned three valid 30-minute books but remained unscored because additional funding was unverified.

Daily prospective replay output now tracks planned lots, modeled IOC attempts, unsent lots, fill outcomes, occupied slots and unavailable or unreplayed slots for each arm. All 249 tests passed. The 08:40 IST pre-window smoke used five valid public observations. The baseline branch planned four lots and modeled three full fills and one zero fill. The four-READY branch planned no lots. No resulting P&L was modeled without settlement evidence. This check is outside the frozen qualification window.

### Trade 92 and review 9 — 19 November, 08:57 IST

The 08:41 four-coin batch closed with four net winners, +$1.11792203 net, $0.49457797 in fees and zero funding. Its BTC and ETH wins are in review 9. XRP +$0.00444541 and SOL +$0.54124395 are trades 91 and 92 and carry into review 10. The observer and workbook verified 92 closes, eight finalized reviews and −$11.51094117 cumulative net. The testnet account is flat at the ninth review gate.

Five specialists and the profitability manager inspected the exact trades 81–90. The independent account read matched 20 fills, 20 commissions and ten cashflows. All ten were WAIT, with two wins, eight losses, +$0.47550000 gross, $1.20837902 commissions, zero funding and −$0.73287902 net. Across all 90 reviewed closes the net was −$12.05663053. Review 9 has no four-READY qualification observation. The manager recommends retaining the ten-minute rule and testing pre-entry movement and execution costs in the frozen prospective window.

The 15-minute comparison finalized with all ten pairs and two wins in each arm. Modeled mean net change versus actual was −$0.05867148. Depth research added no estimates at 15 minutes. At 08:57 IST the 30-minute comparison had four matches, three unavailable and three pending. Its final reference candle matures at 09:12 IST. Record the review against the fresh digest after both pending counts are zero.

The copied-ledger archive parity check used a simulated cutoff one hour earlier while the four positions were protected. Full and archived reads matched 180 fills, 269 wallet postings, all 88 then-settled trades, four open positions and the campaign risk computation.

### Review 9 finalized — 19 November, 09:12 IST

The ninth review was recorded against its terminal evidence digest at 09:12:48 IST. The 30-minute candle comparison paired seven trades. Those trades had two actual winners and three modeled winners, −$0.47104197 actual net and +$1.60691705 modeled net. Three estimates remained unavailable because additional funding could not be verified. Depth evidence added no matches at either horizon.

Across 90 reviewed trades, the 15-minute comparison matched 49 entries with 11 actual winners, nine modeled winners and mean net change −$0.07226670. The 30-minute comparison matched 37 entries with eight actual winners, 11 modeled winners and mean net change −$0.00943678. The CEO retained the 10-minute timer and the registered prospective test. The nine reviewed groups are based on settled exchange trades, with both later wins from the 08:41 batch reserved for group 10.

### Workbook export recovery — 19 November, 09:20 IST

The exact nine-review input reproduced a stalled XLSX export while the execution observer continued monitoring positions. Workbook construction completed in under one second. The failure was isolated to exporting the combination of worksheet formulas and current review data. The export now writes each modeled-minus-actual difference directly from the same verified snapshot, keeping missing comparisons blank. Overview formulas and all review text are retained.

The failing fixture exported in 3.56 seconds after the change. Independent XLSX checks matched 92 verified trades, nine reviews, review 9 net −$0.73287902 and cumulative net −$11.51094117. The live workbook then exported the same totals. Its 88 comparable difference values matched the source cells and 102 non-comparable difference cells were blank.

The next Delta demo batch filled BTC, ETH and XRP at three contracts each, with protection verified. SOL filled zero. Combined planned risk is $4.4489994. Timed exits are due at 09:24:14–09:24:17 IST. The 15- and 30-minute public depth captures were started separately.

### Pre-entry cost diagnostic — 19 November, 09:02 IST

Among 92 settled trades, 22 had both an original signal timestamp and a saved preflight quote. Testnet candle history matched the original signal close for each. The diagnostic compared the last closed ten-minute price change with the planned round-trip fee allowance plus the recorded spread. It used no post-entry prices in the feature. One position exceeded that hurdle and earned $0.09636144 net. The other 21 had six net winners and −$0.97019790 combined. This retrospective subset contains related baskets within one session and lacks coverage of idle opportunities and unsent or unfilled orders. It identifies a pre-entry feature to track prospectively. It does not qualify a filter or timer change.

### Trades 93–95 and workbook scale check — 19 November, 09:33 IST

The 09:24 timed exits for BTC, ETH and XRP reconciled as three net winners. Six fills and nine wallet postings matched the lot sizes, with $0.26066902 commissions, zero funding and +$0.33333098 verified net. The SOL entry had zero fills. The ledger and Excel overview matched at 95 closes, nine finalized reviews and −$11.17761019 cumulative net.

The three 15-minute public depth captures for this batch were usable. The modeled after-cost total was +$0.73348264 on the same three entries, including an XRP estimate for its empty candle reference. All three entries were net winners at both horizons. The displayed-depth estimates remain separate from the candle-based review evidence.

The repaired workbook exporter completed an isolated fixture of 10,000 trades, 1,000 reviews and 20,000 exit comparisons in 109.094 seconds. The exported counts, table extents and cumulative net matched the fixture. The fixture contributed zero campaign trades.

The registered four-READY replay reported zero prospective observations and an awaiting-start state. The frozen window opens on 20 November at 00:00 IST. The recorder, deadline-book process, public funding recorder and protective-price recorder were live. The production demo rules and registered criteria were unchanged.

### Trades 96–99 — 19 November, 09:36 IST

Delta India testnet independently confirmed four entry fills and four exit fills at three contracts each for batch `demo-1795060517840281100`. The twelve matched wallet postings show $0.50144219 in commissions, zero funding, and +$1.97505781 net. BTC earned +$0.69534690, ETH +$0.34032164, XRP +$0.01190798 and SOL +$0.92748129. All four closes were timed. Exit submissions occurred 0.926–5.809 seconds after their individual first-fill deadlines.

The ledger and workbook matched at 99 verified closes, nine finalized reviews and −$9.20255238 cumulative net. Review 10 has nine of its ten verified closes. The demo account was flat immediately after this settlement. The next two attempts stopped before submission because the BTC quote or mark moved outside the saved bounds. The observer remained live with the registered quote guard.

The following attempt filled batch `demo-1795061226753111400`, with three contracts each for BTC, ETH, XRP and SOL. The observer verified all four brackets and $7.6964948 total planned loss including fees. Timed exits are scheduled for 09:47:07.993–09:47:14.667 IST. Separate read-only 15- and 30-minute depth capture sessions were started for this batch.

### Batch 39 paired 15-minute estimate — 19 November, 09:41 IST

The public book capture recorded four valid snapshots for `demo-1795060517840281100`. The official candle method had three usable pairs. A separate displayed-depth estimate recovered SOL when the reference candle contained no trade. On all four matched entries, the 15-minute model had four after-cost winners and +$1.01322881 total, versus four winners and +$1.97505781 realized at ten minutes. The paired mean change was −$0.24045725 per trade. The independent strategy sample still begins at its registered time.

### Trades 100–103 and review 10 — 19 November, 09:48 IST

All four positions in the 09:37 BTC, ETH, XRP and SOL batch exited on their individual timers. Eight exchange fills and twelve matched wallet postings reconciled to $0.50212162 in commissions, zero funding and −$2.08012162 net. The account is flat. Workbook and ledger match at 103 verified closures, nine finalized reviews and −$11.28267400 cumulative net. The observer is live at the automatic review gate.

Review 10 covers closes 91–100 across four distinct baskets. An independent paginated Delta India testnet read matched 20 fills, 20 commissions and ten cashflows. The group had nine winners and one loser, +$3.21600000 gross, $1.20282028 commissions, zero funding and +$2.01317972 net. Without its largest winner it was still +$1.08569843. Nine members entered on WAIT and one on READY. Closes 101–103 carry over to review 11.

The last included position is BTC from 09:37:07.993 IST. Its 15- and 30-minute reference minutes complete around 09:53 and 10:08 IST, respectively. At the first team handoff, the official review still had one pending 15-minute observation and five pending 30-minute observations. Three 30-minute public books for the 09:14 batch were captured, but those comparisons remain unavailable because incremental funding was unverified. Keep the review tied to its fresh digest once both pending counts are zero.

Five specialist findings, the profitability manager's recommendation and the CEO's retain-current decision are preserved in `runs/trade1/review10-team-draft.json`. The draft passed the review schema check and matches the exact ten order IDs. The largest correlated basket accounts for $1.97505781 of the group's profit. The first 100 trades have 27 winners and −$10.04345081 net. The registered research should track IOC fillability across breakout breadth without changing the frozen protocol.

At 09:53:54 IST, the official 15-minute comparison had seven pairs, no pending rows and three unavailable. Both horizons had six winners on those pairs, with modeled mean improvement of $0.07900706. A separate depth-based extension covered all ten with nine winners in each arm and only $0.00071055 mean improvement. The 30-minute official comparison had one pair, five pending, and four unavailable. Keep the review gate until the remaining reference minutes settle and the current digest is verified. PID 11248 remained live and the account was flat.

### Review 10 finalized — 19 November, 10:09 IST

The observer published the terminal digest `6b692712bc50c049d2edb4f9d161dfc4fe656e3f005650473721ede077c96c25`. A fresh Delta India testnet audit matched 20 fills, 20 commissions and ten cashflows for review 10. The five specialist findings, manager recommendation and decision to retain the 10-minute timer were recorded at 10:08:48.700 IST. The sole prospective four-READY registration remains unchanged.

The 15-minute official comparison matched seven entries, with six winners in each arm and +$0.07900706 mean net change. The separate depth extension matched all ten, with nine winners in each arm and +$0.00071055 mean change. At 30 minutes six entries matched, with five winners in each arm and −$0.01027367 mean change. Four 30-minute results were unavailable. Across the first 100 trades, the official 15-minute comparison matched 56 entries with 17 to 15 winners and −$0.05335748 mean change. The 30-minute comparison matched 43 with 13 to 16 winners and −$0.00955355 mean change.

Independent workbook checks matched 103 verified trades, ten finalized reviews, −$11.28267400 cumulative net and review 10's nine wins, one loss and +$2.01317972 net. Weekly quota was 83% remaining. The five-hour view was unavailable.

The observer cleared its review gate and filled BTC, ETH, XRP and SOL at three contracts each in batch `demo-1795063166677196500`. Both bracket orders were verified for each position. Total planned risk including fees was $7.7031326. Individual timed exits are due at 10:19:27.902–10:19:33.718 IST. Public 15- and 30-minute captures were started for the same batch.

### Trades 104–107 and repository sync — 19 November, 10:20 IST

A Windows sharing lock temporarily prevented replacement of `trade1.xlsx`. Exchange-side brackets and the observer remained active. Once the lock was released, the existing export retry refreshed Excel without a worker restart.

The four positions in batch `demo-1795063166677196500` each closed on their original timers. Eight fills and twelve wallet postings matched $0.50393605 in commissions, zero funding and −$0.08393605 net. Excel matches 107 verified closes, ten finalized reviews and −$11.36661005 cumulative net.

The following batch `demo-1795063794635876100` filled three contracts each for BTC, ETH, XRP and SOL. All four brackets were verified. Fees-inclusive planned risk was $7.7069942 and timed exits are due from 10:29:56 to 10:30:02 IST. The 15- and 30-minute public depth captures are scheduled.

The Trading project rule book records `prarit0097/trading18nov` as the canonical GitHub repository. Publish verified demo workbooks, research, rules and project changes at each checkpoint. Keep local execution state and private account responses on the workstation.

At 10:25 IST the 15-minute public depth estimate for the four trades in batch `demo-1795063166677196500` paired all four. It recovered XRP's empty candle reference. The 10-minute result was three winners and −$0.08393605 net. The modeled 15-minute result was two winners and −$0.94752674 net. This estimate is tracked as research.

### Trades 108–111 and review 11 — 19 November, 10:31 IST

The four positions in `demo-1795063794635876100` each closed after their original timer. Eight fills and twelve wallet postings matched $0.50348603 in commissions, zero funding and −$0.98198603 net. Delta India testnet confirmed the account was flat. Excel and the ledger agree at 111 verified trades, ten finalized reviews and −$12.34859608 cumulative net.

The independent signed-account audit for review 11 matched 20 fills, 20 commissions and ten wallet cashflows across closes 101–110. The three baskets produced three wins and seven losses. Gross P&L was −$0.68850000, commissions were $1.06717395 and funding was zero, for −$1.75567395 net. Average net was −$0.175567395 and the group drawdown was $1.75567395. Close 111 was SOL at −$0.54947132 and belongs to review 12.

The six WAIT closes in review 11 earned +$0.03051917. The four READY closes lost $1.78619312 across two baskets, including three carryovers from the same 09:37 basket assessed in review 10. Three total baskets and shared exposure limit inference. Across the first 110 trades there are 30 winners and −$11.79912476 net. The frozen prospective test begins on November 20 at 00:00 IST.

The last included fill was XRP at 10:19:59.845 IST. Its 15- and 30-minute boundary candles finish at 10:35 and 10:50 IST. The observer entered the review gate and remained live. No candidate qualified for promotion.

At 10:36 IST the five specialist findings, profitability manager recommendation and draft decision were validated against the exact group and saved in `runs/trade1/review11-team-draft.json`. The official 15-minute sample matched six entries. Wins fell from two to one and mean net fell by $0.10301677. Displayed-depth estimates covered eight entries, with wins falling from three to two and mean net falling by $0.07725274. The official 30-minute sample still has seven pending observations. The longer hold and broader breakout hypotheses remain research.

### Review 11 finalized — 19 November, 10:52 IST

The observer produced terminal digest `fc5200b263f66207a2cfd35a464aa76e65b6b1edd0977a2d13811c6903f17a96`. A fresh signed Delta testnet audit matched 20 fills, 20 commissions and ten cashflows. Review 11 was recorded at 10:51:41.565 IST with the five specialist findings and profitability manager recommendation. The CEO retained the three-contract, ten-minute demo baseline and the frozen four-READY protocol.

The official 15-minute comparison had six pairs, with wins falling from two to one and mean net falling by $0.10301677. At 30 minutes four entries matched, with one modeled win and +$0.25094455 mean net change. The matched model still lost $0.33929381 after costs. Six official 30-minute observations were unavailable. Supplemental depth added two pairs at 15 minutes and one at 30 minutes. Five hypothetical funding adjustments remain unverified. Across the first 110 trades, official 15- and 30-minute estimates paired 62 and 47 entries and changed average net by −$0.05816322 and +$0.01261650, respectively. Both modeled aggregates lost money.

The next basket `demo-1795065735250059600` filled BTC, ETH, XRP and SOL at three contracts each. The observer confirmed all four stop-loss and target pairs, with $7.6892738 total planned risk including fees. First-fill deadlines are 11:02:16.441–11:02:22.248 IST. Read-only 15- and 30-minute depth captures are scheduled. The latest verified weekly quota was 82% remaining and the five-hour view was unavailable.

### Trades 112–115 — 19 November, 11:03 IST

Delta India testnet independently confirmed eight fills at three contracts per side for batch `demo-1795065735250059600`. Twelve wallet postings establish +$0.09150000 gross, $0.50254455 commissions, zero funding and −$0.41104455 net. All four positions exited on their original timers. BTC, ETH, XRP and SOL netted −$0.20945657, −$0.01375960, −$0.00160079 and −$0.18622759, respectively. Their exits were submitted 0.965–3.895 seconds after deadline.

Workbook and ledger match at 115 verified closes, eleven finalized reviews and −$12.75964063 cumulative net. Review 12 has five verified closes.

The next batch `demo-1795066360590446300` filled BTC, ETH, XRP and SOL at three contracts each. All four protections were verified. Fees-inclusive planned risk is $7.6908212. Individual deadlines are 11:12:41.811–11:12:47.470 IST. The public 15- and 30-minute depth captures were started for this batch.

### Trades 116–119 — 19 November, 11:14 IST

The public 15-minute research comparison for the preceding batch `demo-1795065735250059600` matched all four entries, including a displayed-depth estimate for XRP. Actual 10-minute net was −$0.41104455 with zero winners. Modeled 15-minute net was +$0.16911272 with two winners. The four related positions came from one basket.

The four positions in `demo-1795066360590446300` closed on their original timers. A direct Delta India testnet read matched eight fills at three contracts per side. Twelve wallet postings give −$0.27450000 gross, $0.50252704 commissions, zero funding and −$0.77702704 net. Exit submissions were 2.457–5.282 seconds after the deadline. Workbook and ledger match at 119 verified closes, eleven finalized reviews and −$13.53666767 cumulative net. One more close completes review 12 membership.

The next batch `demo-1795066987122547900` filled three contracts each for BTC, ETH, XRP and SOL. Both protections were verified for all four positions. Fees-inclusive planned risk is $7.6879454 and the original deadlines are 11:23:08.658–11:23:14.457 IST. Public 15- and 30-minute depth captures were started.

### Trades 120–123 and review 12 — 19 November, 11:24 IST

The four positions in `demo-1795066987122547900` closed on their original timers. Eight fills and twelve wallet postings reconcile +$0.27900000 gross, $0.50246252 commissions, zero funding and −$0.22346252 net. The signed Delta India testnet positions endpoint confirmed the account was flat. Workbook and ledger match at 123 verified closes, eleven finalized reviews and −$13.76013019 cumulative net.

The independent review 12 audit matched 20 fills, 20 commissions and ten wallet cashflows for the exact closes 111–120. All ten entered on WAIT and closed at a net loss. Four source baskets contributed one, four, four and one position. Gross was −$0.48750000 and fees were $1.44722867, for −$1.93472867 net. Funding was zero. The first 120 verified trades have 30 net winners and −$13.73385343 total net. Closes 121–123 carry forward to the next group.

The public 15-minute replay for `demo-1795066360590446300` matched four entries using two supplemental depth prices. It moved total net from −$0.77702704 realized to −$0.86957587 estimated, with zero winners in either arm. The 30-minute replay for `demo-1795065735250059600` paired four and moved net from −$0.41104455 realized to −$0.89329109 estimated, also with zero winners. The last included review 12 entry is BTC at 11:13:08.658 IST. Its final 15- and 30-minute boundary candles finish at 11:29 and 11:44 IST.

At 11:30 IST, the five specialist findings, profitability manager recommendation and draft decision were validated against the exact ten orders in `runs/trade1/review12-team-draft.json`. Seven official 15-minute pairs went from zero to two wins and gained $0.05308894 mean net per trade. Supplemental depth covered all ten and raised aggregate modeled net by $0.32008145 to −$1.61464722. The two modeled winners were in one basket. The draft retains the ten-minute timer and records a prospective relative-volume and pre-entry cost diagnostic. The last official 30-minute reference remains due at 11:44 IST.

### Review 12 finalized — 19 November, 11:47 IST

The observer published terminal digest `690e314e60555337db472644a1547a89ee8a67ba953616471732dedc5a08d0ce`. The fresh signed Delta audit matched 20 fills, 20 commissions and ten cashflows. The review recorded all five specialist findings, the profitability manager recommendation and the decision to retain the existing 10-minute baseline at 11:45:40.910 IST. Excel matched 123 closes, twelve finalized reviews, −$13.76013019 cumulative net and the review's ten losses and −$1.93472867 net.

The official 15-minute comparison matched seven entries, going from zero to two wins and +$0.05308894 mean net change. The 30-minute comparison matched two, with zero wins at either horizon and −$0.21758128 mean net change. It had eight unavailable estimates. Supplemental depth covered all ten at 15 minutes and five at 30, with mean net changes of +$0.03200814 and −$0.15622675. Five hypothetical incremental funding amounts remained unverified. Across the first 120 closes, the official 15-minute comparison matched 69 and changed mean net by −$0.04687677. The 30-minute comparison matched 49 and changed mean net by +$0.00322067. Both modeled samples lost money. The existing prospective test remains registered and is awaiting November 20 at 00:00 IST.

Batch `demo-1795068982360404400` filled ETH, XRP and SOL at three contracts each. The BTC IOC filled zero. The observer verified stop-loss and target orders on all three open positions. Fees-inclusive planned risk is $4.9201050. Their first-fill deadlines are 11:56:25.164–11:56:28.983 IST. The public 15- and 30-minute depth captures were started. Weekly quota was 81% remaining and the five-hour reading was unavailable.

### Trades 124–126 — 19 November, 11:58 IST

The three filled positions in `demo-1795068982360404400` closed on their original timers. The signed Delta India testnet endpoint confirmed six fills at three contracts per side. Nine wallet postings give −$0.16050000 gross, $0.30191577 commissions, zero funding and −$0.46241577 net. ETH, XRP and SOL netted −$0.04841812, −$0.00161195 and −$0.41238570 respectively. The earlier BTC IOC had no fill. Workbook and ledger match at 126 verified closes, twelve finalized reviews and −$14.22254596 cumulative net. Review 13 has six verified closes.

Two attempts stopped before submission when BTC fell outside the saved quote bounds. A new attempt `demo-1795069701135640000` obtained fresh quotes and filled BTC, ETH, XRP and SOL at three contracts each. Both bracket orders were verified on all four. Combined planned risk was $7.7135570 including fees. The individual first-fill deadlines are 12:08:22.466–12:08:27.874 IST. Read-only 15- and 30-minute depth captures were started.

### Trades 127–130 and review 13 — 19 November, 12:09 IST

All four positions in `demo-1795069701135640000` closed on their original timers. Eight fills and twelve wallet postings match −$0.05550000 gross, $0.50458201 commissions, zero funding and −$0.56008201 net. The signed Delta India testnet positions endpoint confirmed the account was flat. Workbook and ledger match at 130 verified closes, twelve finalized reviews and −$14.78262797 cumulative net.

Review 13 covers exactly closes 121–130, with no later carryovers. The signed Delta audit matched twenty fills, twenty commissions and ten cashflows. All ten entries were WAIT. The three source baskets contributed three, three and four positions, with the first shared with review 12. Gross +$0.05850000 less $1.10727454 commissions and zero funding yielded −$1.04877454 net, two wins and eight losses. Across the first 130 trades there are 32 winners across 41 source baskets.

The 15-minute replay for `demo-1795068982360404400` paired three entries using one displayed-depth fallback. Its modeled result was one win and −$0.31374501, compared with zero wins and −$0.46241577 realized. The last reviewed SOL entry is 11:58:27.874 IST. Its final boundary candles finish at 12:14 and 12:29 IST for 15 and 30 minutes respectively. The observer is active at the review gate.

At 12:14 IST, all five specialist findings and the profitability manager recommendation were verified against the exact ten orders and saved in `runs/trade1/review13-team-draft.json`. The official 15-minute comparison matched six entries with no winners at either duration and +$0.02066777 mean net change. The supplemental depth method covered all ten with two winners at each duration and +$0.01487555 mean net change. Modeled totals remained negative. The draft retains the 10-minute timer and proposes prospectively comparing price movement to costs at different levels of executable depth and relative volume. Seven official 30-minute observations remain pending, with the last reference due around 12:29 IST.

### Review 13 finalized — 19 November, 12:32 IST

The observer published terminal digest `7b8d41c98de7f4d026114a292fbeea88cb33578534c4bd02e87cbe2870839164`. The signed Delta India testnet audit matched twenty fills, twenty commissions and ten wallet cashflows. At 12:30:51.784 IST the five specialist findings, manager recommendation and decision to retain the existing 10-minute timer were recorded.

Official 15-minute estimates matched six entries with zero winners in both arms and +$0.02066777 mean net change. Official 30-minute estimates matched five entries, with wins increasing from one to two and total net improving from −$0.77030897 to −$0.14903529. The supplemental depth method increased 30-minute coverage to seven entries, with one realized and four modeled winners and modeled net −$0.07581748. Three incremental funding amounts were unverified. Across the first 130 closes, 75 official 15-minute pairs changed mean net by −$0.04147321, and 54 official 30-minute pairs changed mean net by +$0.01442753. Both modeled aggregates were net negative. The existing frozen candidate and limits remain in effect.

Batch `demo-1795071688161949600` filled BTC, ETH, XRP and SOL at three contracts each. All four pairs of stop-loss and target orders were verified. Combined planned risk including fees is $7.7353076. Individual first-fill deadlines are 12:41:29.489–12:41:35.086 IST. The 15- and 30-minute public depth captures were started. Weekly quota was 81% remaining and the five-hour reading was unavailable.

### Trades 131–134 — 19 November, 12:43 IST

The signed Delta India testnet fills endpoint confirmed eight fills at three contracts per side in `demo-1795071688161949600`. Twelve wallet postings match −$0.48750000 gross, $0.50583888 commissions, zero funding and −$0.99333888 net. BTC, ETH, XRP and SOL all closed on their original timers. Workbook and ledger match at 134 confirmed closes, thirteen finalized reviews and −$15.77596685 cumulative net. The four closes will carry into review 14.

The first next-batch attempt stopped before submission after BTC moved outside the saved quote bounds. The following attempt `demo-1795072359995157600` filled three contracts each for ETH, XRP and SOL. BTC filled zero. Stop-loss and target orders were verified for the three open positions. Fees-inclusive risk was $4.9241106 and their first-fill deadlines are 12:52:42.512–12:52:46.328 IST. The public 15- and 30-minute depth captures were started.

### Trades 135–137 — 19 November, 12:54 IST

The public 15-minute comparison for `demo-1795071688161949600` matched all four entries. It gave −$1.94900390 modeled net versus −$0.99333888 realized at ten minutes. There were no winners in either arm.

The three filled positions in `demo-1795072359995157600` all closed on their original timers. The signed Delta India testnet read confirmed six fills, with three contracts per side for ETH, XRP and SOL. Nine wallet postings reconcile −$0.27900000 gross, $0.30229090 commissions, zero funding and −$0.58129090 net. Excel and the ledger match at 137 verified closes, thirteen finalized reviews and −$16.35725775 cumulative net. The next three verified closes will complete review 14 membership.

Batch `demo-1795072981751446300` filled three contracts each for BTC, ETH, XRP and SOL. Both protection orders were verified for each position. Combined planned risk was $7.7165684 including fees. Their individual deadlines are 13:03:02.998–13:03:08.583 IST. The 15- and 30-minute public depth captures were started.

### Trades 138–141 and review 14 — 19 November, 13:04 IST

All four positions in `demo-1795072981751446300` closed on their original timers. Eight fills and twelve wallet postings match −$1.19100000 gross, $0.50424826 commissions, zero funding and −$1.69524826 net. The signed Delta account endpoint confirmed the account was flat. Excel and ledger match at 141 verified closes, thirteen finalized reviews and −$18.05250601 cumulative net.

Review 14 covers exact closes 131–140. Independent Delta India testnet read matched 20 fills, 20 commissions and ten wallet cashflows. Three source baskets contributed four, three and three positions. The last shares SOL close 141 with review 15. Gross −$1.13850000 and commission $1.07124403 produced −$2.20974403 net, with no winners and zero funding. Two reviewed READY entries lost $0.83813838 and eight WAIT entries lost $1.37160565. The first 140 closes have 32 winners across 44 source baskets and −$16.99237200 net.

The 15-minute replay for `demo-1795072359995157600` matched three entries, with zero winners and −$1.22844608 estimated net compared with −$0.58129090 realized. The 30-minute research comparison for `demo-1795071688161949600` matched all four with two depth fallbacks. Both holds had zero winners and the estimated 30-minute net was −$2.79712881 versus −$0.99333888 realized. The final included XRP fill was 12:53:06.534 IST. Its 15- and 30-minute boundary candles finish at 13:09 and 13:24 IST. The observer is active at the review gate.

At 13:09 IST, all five specialist tracks, manager synthesis and the draft decision were validated against the exact order list in `runs/trade1/review14-team-draft.json`. The official 15-minute comparison matched nine entries with zero winners and −$0.16203850 mean change. Supplemental depth covered all ten with zero winners and −$0.14583150 mean change. The draft retains the 10-minute timer and proposes testing whether the observed breakout remains above the reference high at the pre-submit quote. Six official 30-minute observations are pending, with the final reference due at 13:24 IST.

### Review 14 finalized — 19 November, 13:27 IST

The observer published terminal digest `ae41b417d581879efda3c56e522d6c87acc498e8bd0a29cf105b7e2a008b12b5`. A fresh signed Delta India testnet audit matched twenty fills, twenty commissions and ten wallet cashflows. Review 14 was recorded at 13:25:15.742 IST with the decision to retain the ten-minute demo exit and frozen four-READY candidate. Excel matched 141 closes, fourteen finalized reviews and −$18.05250601 cumulative net.

Official 15-minute comparisons matched nine entries and official 30-minute comparisons matched seven. Neither horizon had a winner. The 30-minute modeled net was −$4.16996098 versus −$1.88010154 settled for the same seven. Supplemental depth extended the 30-minute coverage to nine and reduced modeled mean net by $0.26792257. One 30-minute estimate still lacked an executable reference price. Across the first 140 closes, the official 15-minute comparison paired 84 with mean change −$0.05439092, and the 30-minute comparison paired 61 with mean change −$0.02476677. Both modeled aggregates were negative.

After the review gate cleared, one BTC quote guard stopped the first attempt before submission. Batch `demo-1795074991923931100` subsequently filled BTC, ETH and XRP at three contracts each. The SOL IOC was unfilled. Stop-loss and target orders were verified on all three positions. Combined planned risk including fees was $4.4838330 and first-fill deadlines are 13:36:33.186–13:36:36.835 IST. Public 15- and 30-minute depth captures were started. Weekly Codex quota was 80% remaining and the five-hour reading was unavailable.

### Trades 142–144 — 19 November, 13:38 IST

The three filled positions in `demo-1795074991923931100` closed on their original timers. The signed Delta India testnet read confirmed six fills at three contracts per side for BTC, ETH and XRP. Twelve wallet postings reconcile −$0.23100000 gross, $0.26342331 commissions, $0.02482762 funding paid and −$0.51925093 net. The workbook and ledger match at 144 verified trades, fourteen finalized reviews and −$18.57175694 cumulative net. Review 15 now has four verified trades.

The next attempt had an unfilled BTC IOC and an ETH quote guard blocked the unsent legs. The following attempt `demo-1795075665522060600` filled three contracts each for BTC, ETH, XRP and SOL and verified each stop-loss and target pair. The combined planned risk including fees was $7.7095934. Individual deadlines are 13:47:46.796–13:47:52.429 IST. The 15- and 30-minute public depth captures were started.

### Trades 145–148 — 19 November, 13:49 IST

The 15-minute research comparison for `demo-1795074991923931100` paired BTC and XRP. Both remained losses, with −$0.40189292 modeled net and −$0.43538812 realized. ETH's reference lacked an executable price.

The signed Delta India testnet endpoint matched eight fills, each three contracts per side, for `demo-1795075665522060600`. Twelve wallet postings establish +$0.24900000 gross, $0.50449997 commissions, zero funding and −$0.25549997 net. One trade won and three lost. All four closed on their original timers. Excel and the ledger match at 148 verified trades, fourteen finalized reviews and −$18.82725691 cumulative net. Two more closes will complete review 15 membership.

The subsequent batch `demo-1795076296560259600` filled BTC, ETH and XRP at three contracts each and verified both protection orders on all three. The SOL leg stopped before submission on the quote guard. Combined planned risk including fees is $4.4886954 and the individual deadlines are 13:58:18.022–13:58:21.743 IST. The 15- and 30-minute public depth captures were started.

### Trades 149–151 and review 15 — 19 November, 14:01 IST

The three filled positions in `demo-1795076296560259600` closed on their timers. Six fills and nine wallet postings match −$0.45900000 gross, $0.26363357 commissions, zero funding and −$0.72263357 net. Delta India testnet confirmed no open positions. Ledger and workbook match at 151 verified closes, fourteen finalized reviews and −$19.54989048 cumulative net.

Review 15 covers closes 141–150, one winner and nine losses across four related baskets. The signed audit matched twenty fills, twenty commissions, ten cashflows and three funding postings. Gross loss was $1.25400000, commissions were $1.26956539 and funding paid was $0.02482762. Exact net loss was $2.54839301. All ten entries were WAIT. Close 151 is XRP at −$0.00912547 and belongs to review 16. The first 150 verified trades have 33 winners across 47 source baskets and −$19.54076501 net.

In the final basket, ETH close 150 was submitted 13.299637 seconds after its deadline and filled 0.327602 seconds later. XRP close 151 was submitted 12.404680 seconds after its deadline and filled 0.557065 seconds later. BTC's fill preceded ETH's deadline by 82 milliseconds. This is consistent with staggered deadlines across two observer passes. The journal has no row-level check timestamps to confirm the sequence or quantify the P&L effect. All three closes were first attempts.

Final 15- and 30-minute review references mature at 14:04 and 14:19 IST. The observer remains live at the review gate.

At 14:04 IST, five specialists, the manager and CEO draft were validated against the exact order list in `runs/trade1/review15-team-draft.json`. Nine official 15-minute pairs went from one winner to zero and mean net fell $0.04252866. One more price reference was unavailable. A fake-venue replay using staggered first-fill timestamps confirmed that an observer pass can close the first due position and leave two upcoming deadlines for a later pass. It does not recreate the live network sequence. These were the only two send delays above ten seconds across 151 timer exits. Six official 30-minute observations remain pending, with the final reviewed reference due at 14:19 IST.

### Review 15 finalized — 19 November, 14:22 IST

The observer published terminal digest `0bae0340c89e341d026d0699e1ac9b4eeda0dac84aba40ce174c5ac97d5b9fd6`. The fresh signed Delta India testnet audit matched twenty fills, twenty commissions, ten cashflows and three funding postings. The five specialist findings, manager recommendation and decision to retain the ten-minute timer were recorded at 14:20:37.557 IST. Excel shows 151 verified closes, fifteen finalized reviews and −$19.54989048 cumulative net.

Both official comparisons matched nine entries. Each went from one winner to zero. The 15-minute modeled net was −$2.84728810 versus −$2.46453020 realized on its matched entries. The 30-minute modeled net was −$3.78223044 versus −$2.54676832 realized. Supplemental depth recovered one 30-minute reference, so that model matched all ten and gave −$3.78682430 versus −$2.54839301 realized. Across the first 150 closes, 93 official 15-minute pairs changed mean net by −$0.05324295, and 70 official 30-minute pairs changed mean net by −$0.03923193. The frozen four-READY protocol remains registered for November 20.

The first fresh attempt stopped at the BTC quote guard. Batch `demo-1795078327011995800` then filled BTC, ETH, XRP and SOL at three contracts each. All four bracket pairs were verified. Combined planned risk including fees is $7.6922906 and the individual deadlines are 14:32:08.346–14:32:13.861 IST. Public 15- and 30-minute depth captures were started. Weekly quota was 79% remaining and the five-hour reading was unavailable.

### Trades 152–155 — 19 November, 14:33 IST

The signed Delta India testnet fills endpoint confirmed eight fills, with three contracts per side for all four positions in `demo-1795078327011995800`. Twelve wallet postings establish +$1.08900000 gross, $0.50342310 commissions, zero funding and +$0.58557690 net. All four positions won and closed on their original timers. Excel and the ledger match at 155 verified closes, fifteen finalized reviews and −$18.96431358 cumulative net. Review 16 now has five verified members.

Batch `demo-1795078956834119400` then filled BTC, ETH, XRP and SOL at three contracts each. The observer verified all four stop-loss and target pairs. Combined planned risk including fees is $7.7067806. Individual first-fill deadlines are 14:42:38.086–14:42:43.719 IST. Public 15- and 30-minute depth captures were started.

### Trades 152-155 supplemental depth comparison - 19 November, 14:40 IST

The public 15-minute order book report matched all four Trade 1 demo entries from batch `demo-1795078327011995800`. Estimated net was +$1.40632260 versus +$0.58557690 realized on those entries. Both groups had four winners. The executed hold was ten minutes.

### Trades 156–159 — 19 November, 14:44 IST

Delta India testnet confirmed all eight fills in batch `demo-1795078956834119400`. Each of BTC, ETH, XRP and SOL opened and closed three contracts. Twelve matched wallet postings established −$0.19650000 gross, $0.50402446 in commissions, zero funding and −$0.70052446 net. All four closed via their ten-minute timers and ended at a net loss. Close submission delays ranged from 0.868 to 3.766 seconds. The ledger and Excel match at 159 verified closes, 15 finalized reviews and −$19.66483804 cumulative net. Review 16 has nine verified closes.

In batch `demo-1795079582885832200`, the BTC IOC went unfilled and SOL moved outside the saved quote or mark bounds. ETH and XRP filled three contracts each with verified stop and target pairs. Their combined planned risk including fees is $1.6865014 and their respective deadlines are 14:53:05.363 and 14:53:07.485 IST. Both public order book capture workers started for the 15- and 30-minute comparisons. The observer is waiting for that exposure to settle. Weekly quota was 79% remaining and the five-hour reading was unavailable.

### Trades 156–159 supplemental depth comparison — 19 November, 14:48 IST

The 15-minute replay matched all four positions in batch `demo-1795078956834119400`. The public deadline order book supplied a usable SOL reference where the candle method had none. This matched sample had zero winners at both horizons. The modeled net was −$0.63496129 versus −$0.70052446 realized at ten minutes, a $0.06556317 improvement within one correlated basket. The live exit policy remains ten minutes.

### Trades 160–161 and review 16 opened — 19 November, 14:54 IST

Four signed Delta India testnet fills and six matched wallet postings settled ETH and XRP in batch `demo-1795079582885832200`. Both closed three contracts on their ten-minute timers. ETH net was −$0.07994917 and XRP net was −$0.00613823. Together they realized −$0.02550000 gross, $0.06058740 commissions, zero funding and −$0.08608740 net. The account was flat on the signed perpetual-position read. Excel and the ledger match at 161 verified closes, 15 finalized reviews and −$19.75092544 cumulative net.

Review 16 covers closes 151–160. XRP close 161 belongs to review 17. The signed audit matched 20 fills, 20 commission debits and ten cashflows. Review 16 earned $0.86400000 gross with $1.06802220 commissions and zero funding, for −$0.20402220 net and four wins from one of the four represented baskets. The review gate is active. The final included ETH entry's complete reference minutes become eligible at 14:59 and 15:14 IST for the 15- and 30-minute estimates.

The supplemental 30-minute depth replay for trades 152–155 matched three of four entries. It added XRP and lacked a valid SOL snapshot. The three matched positions yielded +$0.35499686 modeled versus +$0.30671051 realized, with three winners at both horizons. This comparison does not add to realized results.

### Review 16 team findings — 19 November, 15:00 IST

The five specialists and profitability manager completed the draft for closes 151–160. Gross profit of $0.86400000 fell short of $1.06802220 in fees. All four winners came from one basket. The manager's next research test measures displayed quantity inside each existing IOC cap and compares expected fill size with actual outcomes. The CEO retained the ten-minute rule, IOC guards and frozen four-READY protocol.

Eight official 15-minute pairs stayed at four winners and gained $0.08257828 on average. Supplemental depth raised coverage to all ten with four winners at both horizons and a $0.07592137 mean change. Across the first 160 closes, 101 official 15-minute pairs changed mean net by −$0.04248484 and reduced wins from 24 to 22. The observer is flat at 161 verified closes while five 30-minute outcomes remain pending. The last complete reference minute becomes eligible at 15:14 IST.

### Trades 156–159 supplemental 30-minute comparison — 19 November, 15:03 IST

The 30-minute replay matched BTC, ETH, XRP and SOL from batch `demo-1795078956834119400`. The candle model supplied all four estimates. The SOL deadline order book was unavailable. This basket had zero winners at both horizons and modeled net of −$1.62094396 versus −$0.70052446 realized at ten minutes.

At this snapshot Review 16 had six official 30-minute pairs, two wins at each horizon and mean net change of −$0.14560914. Supplemental depth supplied eight pairs with three wins at each horizon and mean net change of −$0.10938760. One official outcome remained pending. The observer remained flat at 161 verified closes and 15 finalized reviews.

### Review 16 finalized — 19 November, 15:16 IST

The observer published terminal evidence digest `f370911a133ec17c2f97b6f9c3ecc684418759864de3c6131eed7bebad245c7c`. A fresh signed Delta India testnet audit matched 20 fills, 20 commissions, ten cashflows and zero funding for the ten verified closes. The profitability manager confirmed retain-current after seeing the final pairs. The CEO recorded all five findings, the decision to retain the ten-minute policy and the unchanged frozen four-READY validation at 15:16:12.365 IST.

The 15-minute candle comparison matched eight closes, with four winners at both horizons and +$0.08257828 mean modeled change. Supplemental depth gave ten pairs and +$0.07592137 mean with the same four winners. The 30-minute candle comparison matched seven closes, moving from two to three winners while mean net fell by $0.11197187. Supplemental depth gave nine pairs, moving from three to four winners with mean net down $0.08724990. Across the first 160 closes, 101 official 15-minute pairs changed mean net by −$0.04248484 and 77 official 30-minute pairs changed it by −$0.04584465. The manager prioritized measuring executable quantity inside unchanged IOC caps in prospective observations.

After the gate cleared, batch `demo-1795081590539352000` filled exactly three contracts each in BTC, ETH, XRP and SOL. The signed India testnet read confirmed the four positions and all eight reduce-only stop and target orders. Combined planned risk including fees was $7.7113544. Deadlines are 15:26:31.764–15:26:37.602 IST. Both public 15- and 30-minute capture workers started. Excel shows 161 verified closes, 16 finalized reviews and −$19.75092544 cumulative net. Weekly quota was 78% remaining and the five-hour reading was unavailable.

### Trades 162–165 — 19 November, 15:28 IST

Batch `demo-1795081590539352000` settled all four three-contract positions on their ten-minute timers. A signed Delta India testnet read matched eight fills. Twelve wallet postings establish −$0.11550000 gross, $0.50438767 in fees, zero funding and −$0.61988767 net. All four closed at a net loss. Submission delays ranged from 1.728 to 7.453 seconds. Excel shows 165 verified closes, 16 final reviews and −$20.37081311 total net. Review 17 has five verified closes.

The next batch `demo-1795082222536893200` filled three contracts each for BTC, ETH, XRP and SOL. The signed read confirmed the four fills and all eight reduce-only protection orders. Combined planned risk including fees is $7.7104772. The deadlines range from 15:37:03.724 to 15:37:09.295 IST. Both public order-book capture workers started. Daily loss plus reserved risk was $28.08129031 against the $30 limit. Weekly quota was 78% remaining and the five-hour reading was unavailable.

### First IOC depth observation — 19 November, 15:29 IST

A bounded public testnet order-book probe captured 2,488 offer snapshots across five symbols and two connections. For the four IOC submissions in batch `demo-1795082222536893200`, the last eligible snapshots arrived 257–493 ms before the journaled submission starts. Each showed at least three displayed contracts within the saved cap. All four signed exchange fills matched those quantities. The matched levels, clocks and limits are in `runs/trade1/ioc-probe-20261119-1524.json`.

This single correlated basket provides a check of the measurement method. It contains no partial, zero-fill or guarded-unsent observations. No strategy decision relies on this sample.

### Trades 166–169 — 19 November, 15:38 IST

Batch `demo-1795082222536893200` settled four three-contract positions on their ten-minute timers. A signed Delta India testnet read matched eight fills. Twelve wallet postings established +$0.60300000 gross, $0.50468155 commissions, zero funding and +$0.09831845 net. ETH and SOL won after costs. Exit submission delays ranged from 1.413 to 7.385 seconds. The ledger shows 169 verified closes and −$20.27249466 total net. Review 17 has nine verified closes.

The next batch `demo-1795082853511537900` filled three contracts each in BTC, ETH, XRP and SOL. The signed read matched all four fills and eight reduce-only protective orders. Combined planned risk including fees is $7.7171960. Daily loss plus reserved risk amounts to $27.98969066. The 10-minute deadlines range from 15:47:34.830 to 15:47:40.442 IST. Public order-book capture workers started for both longer horizons.

The 15-minute supplemental replay for trades 162–165 produced zero matched estimates. The modeled holds cross a UTC hour boundary and additional funding could not be verified. Order-book depth does not resolve the missing cost. The four actual settlements remain verified.

### Second IOC depth observation — 19 November, 15:39 IST

A second bounded public testnet probe captured 2,486 snapshots across five symbols. The four selected snapshots arrived 263–602 ms before submission started for batch `demo-1795082853511537900`. All four expected quantities matched signed three-contract fills. The matched levels, clocks and IOC limits are in `runs/trade1/ioc-probe-20261119-1535.json`.

Across the two probes, all eight sent lots in two baskets were predicted and realized full fills. The sample contains no partial fills, zero fills or unsent lots. It supports collecting prospective evidence and leaves the registered candidate rules in place.
