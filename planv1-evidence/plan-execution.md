## D. Profit probability ko honestly measure karna

Objective sirf winning-trade percentage maximize karna nahi. Positive average **net** outcome, acceptable drawdown/tail exposure, stable execution aur enough independent historical periods chahiye. A 70% win-rate strategy large losses se negative ho sakti hai; lower win rate with larger realized wins profitable ho sakti hai. Har report mein wins/losses/flat outcomes aur costs ka denominator explicit ho.

Let `W` = mean positive trade outcome **net of all modeled costs**, `L` = absolute mean negative net outcome. For a two-outcome sample with no zero-net trades, `p` is win probability and `E_net = p*W − (1−p)*L`; break-even is `L/(W+L)`. With actual zero-net outcomes, use **unconditional** `E_net = p_win*W − p_loss*L`, with `p_win+p_loss+p_zero=1`. Equivalently, `E_net=(1−p_zero)*[p_cond*W−(1−p_cond)*L]`, where `p_cond=p_win/(1−p_zero)` and p_zero<1. Break-even formula then concerns p_cond, not the unconditional win fraction. If every trade is zero-net, expectancy=0 and p_cond is undefined.

Flat means exactly zero **net** settlement, not zero gross price move, no-fill intent, or TimeMachine “neither”. Neither/timeout positions must close/mark under the declared horizon rule and contribute their actual net outcome. Report no-fill/cancelled intentions separately from executed-trade denominators. Fees already included in W/L must not be subtracted again; gross accounting must include them once. For hypothetical p_win0.40, p_loss0.50, p_zero0.10 and W55.86/L24.99, unconditional expectancy is9.849 quote units, not the value produced by pretending all non-wins are losses. These are accounting identities and fictional inputs, not known BTC/ETH probabilities.

### Fictional worked crypto example — arithmetic only

| Input | Hypothetical value |
|---|---|
| Instrument | BTC/USDT spot; not a current quote or recommendation |
| Entry reference / stressed stop execution | 100,000 / 98,500 USDT per BTC |
| Combined modeled round-trip cost allowance | 200 USDT per BTC, fictional conservative budget; actual venue fee not quoted |
| Trade risk budget / illustrative quantity step | 25 USDT / 0.00001 BTC; actual venue metadata must replace step |
| Per-BTC modeled loss | 1,500 + 200 = 1,700 USDT |
| Quantity before other caps | floor-to-step(25/1,700) = **0.01470 BTC** |
| Modeled loss at that quantity | **24.99 USDT**; gap/failure can lose more |
| Target execution, fictional | 104,000; net win=(4,000−200)×0.01470=**55.86 USDT** |
| Break-even win rate | 24.99/(24.99+55.86)=**30.9091%** for this simplified two-outcome model |

Do not infer a30.9% attainable market hit rate from that payoff ratio. The example omits variable costs/partials/correlation/outages beyond the listed allowance and must still satisfy free cash, exposure, min-notional, depth and order-type checks. No proposed fixed capital-risk percentage is an optimized personal allocation.

### Research protocol and acceptance

- Pre-register a tiny hypothesis set: technical-only baseline; same baseline + liquidity/cost filter; same + verified-news avoidance/selection rule. Freeze parameter search budget. News doesn't automatically supply a buy/sell sign.
- Train/validate only on earlier periods; compare complete equivalent test periods with fees and turnover. The maximum label/holding interval controls overlap purge; rolling feature warmup can read legitimate past data, not future outcomes. Final holdout is consumed once; after reviewing it, future changes need new out-of-sample evidence.
- A historical-news test needs captured `available_at` evidence. Current RSS archive publication time, retrospectively revised articles, current GraphRAG memory and a modern LLM's learned future facts can leak outcomes. Prompting “pretend it is old date” cannot certify removal of model knowledge. Where availability history is missing, start prospective collection and label old study unavailable or exploratory.
- Run feature/agent ablation against an identical cost/fill engine. Report all tested rules/prompts, not only winner. Selection risk is real even with a holdout; multiple-testing assessment and block-aware uncertainty belong in the promotion report. [Primary research on backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
- Analyze base and stressed fees/spread/latency, turnover caps, outage and gap windows, separate BTC/ETH results and combined portfolio. Use a fixed threshold chosen before test. An example research gate is positive net expectancy with a pre-specified block-bootstrap lower confidence bound above0; where sample support fails, status is **inconclusive/no promotion**, not forced PASS. This is a chosen gate, not a guarantee of future returns.
- Compare cash, buy-and-hold and a simple rule on matching periods/capital; buy-and-hold risk differs, so report drawdown/exposure too. Calendar-day count, unique regimes and effective blocks matter alongside trade/path count. Do not manufacture a universal minimum number of trades or annualize a short lucky week into a promise.
- Execution validation precedes profit scoring: same fixture produces identical ledger; no future visibility; no negative free cash; per-fill asset transfer and fee reconciliation; no duplicate fills; sequence-gap rejection; stop/target collision; fee-currency conversion; venue filter rejection; partial/cancel race; unknown order response reconciliation.

## E. News speed: delivery budget, not an impossible global guarantee

End-to-end observed alert delay decomposes into publisher/feed/CDN delay + source discovery + network fetch/push + parse/dedupe/persistence + outbound queue + notification/client display. Local code can reduce only part of this chain. No inspected free source establishes complete, earliest global newswire coverage. News can be priced into BTC/ETH before any public feed alert; execute/no-execute remains a separate tested decision.

For periodic polling interval P, **under healthy, immediate source availability and uniform arrival phase**, expected discovery wait is P/2. A60s poll suggests30s average polling wait;15s suggests7.5s. These are math illustrations, not measured delivery times or permission to poll every15s. Actual worst-case delay is unbounded across source outage, backoff or network failure.

Start source-policy-compliant60–120s RSS polls and documented GitHub budget, then lower interval only after per-source permission/limits/cache behavior and health measurements support it. Verified eligible pushes can remove the polling component. If a source does not publish limits or terms are unclear, do not label aggressive polling as permitted. Authenticated announcement push remains off until free eligibility/account access is verified; bypassing429/IP bans or paying for a feed violates this design.

Proposed **internal** benchmark targets: full feed/message body received→parse/dedupe/durable event+outbox+local publish p95≤250ms and p99≤2s; duplicate/reordered replay produces exactly one initial local event plus explicit revisions; queue overflow and source staleness visible. These are unmeasured targets on stated hardware/load, excluding source waiting and handset arrival. Benchmark before adopting tighter targets. Preserve p50/p95/p99, max, failure/drop counts, sample sizes and busy periods. Publish-time skew should be a diagnostic, not silently clipped to zero latency.

Local dashboard is baseline no-credential delivery; optional phone queue must have client receipts if actual handset latency is claimed. One open feed can miss late edits/deletions: preserve versions and correction/retraction alerts. During network loss, stale label and suspended new-trade eligibility are preferable to apparently current news. Source-health warning frequency must not consume the entire mobile rate budget.

### Required risk configuration before any paper promotion

Fields include max trade-loss quote, max aggregate/open-order reserved risk, asset/gross/venue/quote exposure, rolling-loss/drawdown thresholds, max signal/quote age, risk-decision TTL, spread/depth/participation caps and reconciliation timeout. These are owner/research-policy inputs, not values inferred from a repo example. Unset critical fields block promotion. Price drift/sequence changes require a fresh bounded risk check; high message rates must not be handled by silently relaxing staleness or endlessly starving the queue. Test valid-send and reject behavior under realistic burst loads.

Scenario event weights and synthetic participant mix are assumptions unless calibrated on training data and checked on held-out observations. Counts or vote fractions from an uncalibrated social world cannot become market probabilities. Conditional bootstrap confidence and prospective empirical trade-outcome confidence remain separate reports.

## F. Proposed implementation map

Future code should live in a **new** `crypto-research/` module under Trade, rather than silently changing the inspected source repositories. This directory is a proposal; it has not been created by this plan. Existing repo functions can be reused behind narrow adapters with their source/license obligations preserved.

```text
crypto-research/
  config/        selected venues/pairs, source allowlist, policies; no secret literals
  contracts/     event, proposal, risk decision, order/fill, experiment schemas
  collectors/    market WS/REST/archive and allowed RSS/status/release sources
  storage/       immutable raw/normalized manifests, transactional ledger/outbox
  features/      closed-bar, volume/liquidity and as-of joins
  strategies/    small deterministic baseline; optional research-graph adapter
  replay/        event clock, fills/fees/queue model, cost and fault scenarios
  simulation/    bootstrap ensembles and separate lightweight-agent market world
  risk/          sizing, versioned decisions, reservations, exits and kill switch
  execution/     shadow + paper only by default; reconciliation adapter
  alerts/        local delivery, optional phone outbox and receipt ledger
  evaluation/    walk-forward, ablation, calibration and promotion artifacts
  tests/         data contracts, chronology, accounting, failure and load fixtures
```

Minimal versioned schemas and adapter boundaries first; no Kubernetes, paid message bus or full five-repo deployment required to collect two pairs and a few news feeds. Exact library versions and supported Windows/Linux environment must be pinned during implementation; this research did not certify the proposed new environment.

### Task P0 — Freeze experiment and source eligibility

- [ ] Choose owner-permitted venue, spot and linear-perpetual product IDs, quote/margin currencies, horizon, capital limits and local hardware; user has confirmed comparison of both products, not execution permissions.
- [ ] Record each source API/terms/auth/rate/retention policy, last checked date, attribution and disabled paid/unknown connectors.
- [ ] Test: configuration rejects paid baseline connectors, missing venue metadata and futures-without-margin-model; no private key required for read-only baseline.
- [ ] Deliverable: versioned config/schema/source ledger; no strategy performance score yet.

### Task P1 — Record market truth before building forecasts

- [ ] Create paired BTC/ETH spot and selected linear-perpetual collectors from the start, with product-separated trade/book data. Capture perpetual mark/index and funding schedules/snapshots as-of alongside spot, so equal-period comparison is possible. Bound archive downloads, checksum/units and resumable manifests; use sequence-aware reconnect/backfill. If derivative data is not legally/publicly available, mark that branch unavailable rather than substituting spot prices.
- [ ] Normalize final1m/5m/15m candles; retain partial stream separately. Chart displays observed data, gaps and as-of provenance.
- [ ] Test: ms versusµs, duplicate IDs, missed sequence, out-of-order messages, UTC day boundary, no-trade interval versus outage, incomplete candle, corrupt archive and changed metadata.
- [ ] Deliverable: replayable raw/normalized slice; health status blocks new signals on invalid data. L2 strategy testing waits for actual captured book coverage.

### Task P2 — News collector and fast alerts

- [ ] Implement small verified source allowlist, conditional HTTP polling, source budget, dedupe/versioning, health state and durable outbox.
- [ ] Fast alert sends source/headline/link/trust/time first; optional full body/local summary later. Errors and corrections are explicit.
- [ ] Test: malformed feed, stale/bad timestamp, duplicate/republication, negative/ambiguous ticker, correction/retraction,403/429/5xx, slow source, ETag304, restart/outbox replay, phone unavailable.
- [ ] Deliverable: measured local-stage latency and source-age ledger; independent ground truth is required before source-wide missing-story recall can be claimed.

### Task P3 — Baseline strategy, cost-aware backtest and honest comparisons

- [ ] Implement one tiny deterministic baseline and pre-specified liquidity/news variants with identical live/replay feature functions.
- [ ] Add product-specific fees, spread, latency, fill assumptions and futures funding/margin rules before optimization; choose candle screening or event engine interface explicitly and preserve its semantics.
- [ ] Test: truncating future data cannot change earlier decisions; LLM research gets no future/revised memory; fill cannot precede decision+latency; same price touch doesn't guarantee limit fill.
- [ ] Deliverable: train/validation/test/holdout manifests, all-trials log, net equity/drawdown/tail/turnover/cost/fill metrics and no-edge/inconclusive outcomes retained. Freqtrade lookahead diagnostic is supplementary; its docs note untriggered signal paths can escape detection.

### Task P4 — Crypto Time Machine and parameter uncertainty

- [ ] Add joint-asset contiguous-block/regime sensitivity alongside exact historical replay. Fix horizon definition and stop execution semantics; report terminal underlying prices separately from settled account P&L.
- [ ] Test: block dependence preserved as designed; seed reproducible; gap stop can lose worse than−1R; same-bar ambiguity policy visible; neither/timeout outcome resolved at actual executable price.
- [ ] Deliverable:10,000+ scenario outcomes if compute permits, unique historical-sample count, cost stresses and assumptions. Path count is not evidence count.

### Task P5 —10,000+ lightweight-agent stress world

- [ ] Implement finite-depth matching/accounting with synthetic participants, calibrated only on training data. Sparse social scenarios remain optional/no paid API baseline.
- [ ] Benchmark100→1,000→10,000 agents on stated hardware: events/s, p95/p99 step latency, peak RAM, queue growth and reproducible event ledger. Define resource cap and stop on overload rather than dropping risk events silently.
- [ ] Test: no money/inventory creation, partial fills/cancels, shared-liquidity consumption, order priority, bounded scenario magnitudes and seeded reruns. Synthetic “people” never become real vote samples.
- [ ] Deliverable: capacity/calibration report or explicit capacity failure; no unbenchmarked10k-agent capacity promise.

### Task P6 — Risk state machine and paper reconciliation

- [ ] Implement Decimal sizing, venue filters, fee/stress budgets, portfolio concentration, atomic reservations and short-lived versioned risk decisions.
- [ ] Wire an always-on local paper/shadow executor; any later exchange testnet is optional and separately validated for eligibility/price realism. Live trading remains disabled. Spot and perpetual branches must pass their separate SectionI gates before paper qualification.
- [ ] Test: stale PASS, quote drift, metadata/filter change, concurrent strategies consuming same cash, partial entry/exit protection, cancel/fill race, timeout-unknown state, duplicate request/fill, restart and missing credentials.
- [ ] Deliverable: trustworthy order/fill/account ledger and separate organization compute budget versus trading risk ledger. No trading permission is implied by a Paperclip task approval.

### Task P7 — Independent acceptance and continued forward observation

- [ ] Run all contract/invariant/fault gates, frozen walk-forward evaluation, cost/latency stress and cross-venue robustness where equivalent data exists.
- [ ] Collect prospective shadow decisions with exact first-seen news and market context; compare modeled fills with subsequent recorded trade/book evidence while acknowledging the unobserved own-order counterfactual.
- [ ] Deliverable: versioned promotion dossier listing pass/fail/inconclusive evidence, confidence limits, missing coverage, hardware/cost and explicit remaining risks. A live-capital proposal requires a separate user decision and cannot follow automatically from this plan.

## G. Priorities aur what “better” means

| Priority | Concrete improvement | Metric/gate | Not enough by itself |
|---|---|---|---|
| P0 | Correct clocks, source eligibility, Decimal units | Zero unexplained unit/identity/chronology errors in fixtures | More indicators |
| P1 | Reliable capture/news-first local path | Measured health/coverage/latency distributions, no silent gaps | Faster headline summary |
| P2 | Same signal code + cost/fill accounting | Deterministic ledger, net OOS comparison, turnover/cost stress | Gross backtest return |
| P3 | Atomic risk and reconciliation | No double-spend/duplicate fill; stale versions reject | Same-day PASS file |
| P4 | Bootstrap and10k synthetic stress | Calibration, dependence/seed/hardware evidence, tail exposure | More generated paths or unanimous agents |

“Best” depends on horizon and data coverage. For low-frequency BTC/ETH research, sound candles and realistic fee assumptions are an immediate upgrade. For seconds/ticks/queue-sensitive entries, capture venue trades/book and validate execution first. With free public news, optimize reliable low-latency detection on an explicit source set; do not claim the fastest global newswire. If no strategy survives the protocol, the correct output is **no trade/no demonstrated edge**, which protects capital better than manufacturing confidence.
