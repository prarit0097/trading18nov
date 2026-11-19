# Paper-exit implementation

Spec: PAPER-EXIT-DESIGN.md. Python stdlib3.11+, existing workspace, no live orders or paid services. Preserve earlier research kernel before changing it.

1. Snapshot current `crypto_skills/*.py` and `run.py` under the completed pilot's frozen-code directory with SHA256 manifest; verify old calculation hash from copied validation/research/trade/core files.
2. Failing tests first: public envelope reader integrity; new per-position exit model; shared fee-inclusive close settlement. Refactor existing close without changing prior semantics.
3. Add `watcher.observe(workspace,position_id,quote,now=None)` and `watcher.run(args)`. Quotes are acquired outside the writer lock; observed exits revalidate under it. Legacy archives must be verified and match entry context. Persist durable quote/ledger/watcher evidence and isolate per-position errors. Test all source/freshness/idempotency cases.
4. CLI `paper watch`, duration/poll options, reject historical/manual inputs, include watcher in reports. Update installed paper/workflow/risk/report instructions and docs, preserving truthful bounded-monitoring limits.
5. Full regression suite, official skill validation, compile checks and independent review. Run one60-second real-public-data paper watch on the existing BTC/ETH/SOL account; verify before/after ledger conservation and that no background process remains. Document outcomes without claiming profit probability improvement.
