# Plan V1 implementation scope

Approved input: ../planv1.md and user's request for interconnected skills, Python scripts and shared JSON. New standalone workspace; no existing checkout is modified or installed globally. All commands support --workspace and emit integrity-checked JSON artifacts. Python3.11+ standard library only.

Implementation tasks:
- [x] Define artifacts/core; test missing implementation red, then integrity/lock/decimal green.
- [x] Market/news import and bounded free read-only acquisition, units/closed bars/health/dedupe/poll state, module tests.
- [x] Entry/exit/sizing/risk/paper journal, lineage+TTL+cash gates and idempotency, module tests.
- [x] Historical bar replay, block-bootstrap Time Machine, finite-cash lightweight-agent world, module tests and10k run.
- [x] CLI, demo fixture, 12 SKILL.md entrypoints and script wrappers; artifact contract reference.
- [x] Integration checks, adversarial risk/input cases, skill validators, reproducible demo and final independent review.

Acceptance: run complete deterministic demo, independently invoke separate skill wrappers against same JSON workspace, stop stale/changed/blocked inputs and duplicate paper submission, prove arithmetic/ledger invariants, run10k-agent stress with measured limits, no real order/credential/paid-provider path. Every output labels fixture/import/live-read provenance and research assumptions.

Plan V1 is broader than one skill pack: persistent WebSocket L2 capture, GUI/SSE/mobile delivery, qualified derivatives margin/liquidation execution, real MiroFish/Zep/LLM integration, and full deployment promotion are not silently declared complete. Pack supplies bounded executable research/paper tools with explicit limits. Spot+perpetual research comparison does not justify fake qualified futures paper fills.

Independent review repaired executable fills beyond target, original signal-time expiry, backtest cost-inclusive risk sizing, transitive simulation lineage, pipeline exit status, required artifact timestamps and synthetic/invalid chart reporting. See VERIFICATION.md for the saved test and public-read evidence. The initial build did not globally install skills. The subsequent user-authorized local installation registered all 12 skills and created an isolated environment; see INSTALLATION.md. No live trade was performed.

Follow-on strategy research: implemented bounded historical pagination, signal-plan parity and frozen chronological validation with reuse protection. The60-day pilot rejected all candidates; full walk-forward/purged deployment qualification and automatic exit monitoring remain outside this completed pilot. See PROFIT-RESEARCH-RESULTS.md.

Follow-on bounded paper-exit monitor implemented and verified: see PAPER-EXIT-RESULTS.md. It runs only for an explicitly requested observation interval; no always-on service, real orders or positive-expectancy qualification is claimed.
