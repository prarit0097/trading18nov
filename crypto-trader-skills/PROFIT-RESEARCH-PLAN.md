# Implementation plan: Plan V1 validation pilot

Spec: PROFIT-RESEARCH-DESIGN.md. Existing owner authorization covers this research workflow; open manual paper ledger and risk limits are preserved. Python3.11+ stdlib; no live orders, paid provider, parameter search expansion or profit guarantee.

1. Audit parity: failing signal-price/gap regressions in tests/test_research.py; share `trade.long_levels(entry,stop_pct,target_r,tick)` with research.backtest. Keep next-open fills outside original stop/target unfilled. Run trade/research suites.
2. Build `crypto_skills/validation.py`: tests first for disjoint splits, frozen selection, deterministic metrics/bootstrap, manifest integrity and failed promotion. Public-history download takes explicit end/days, caches parameter-bound raw pages, validates units/continuity and retains hashes. CLI download/evaluate uses a dedicated workspace and never the paper-account ledger.
3. Precommit the four fixed variants,60-day end2026-11-14,30/15/15 windows and qualification gates. Reserve final dates in a shared registry; a new fingerprint reusing overlapping final dates is exploratory and cannot qualify. Identical runs reuse saved envelopes.
4. Run public BTC/ETH/SOL download and evaluation. Store every train trial, frozen choice before validation/test, baseline/cash/capped-hold comparisons, doubled-cost final diagnostics and daily block-bootstrap uncertainty. All boundaries force settle with costs; no future outcome exclusion.
5. Update skill guidance/reporting with a reference to actual research results and its limits; retain current defaults unless evidence gates pass. Verify complete regression suite and source/data manifests, perform final review, publish a concise result report.

Review focus: no training access to holdout metrics; different run IDs cannot rehabilitate reused final dates; future/unclosed/gapped input fails; invalid next-open prices do not reset a trade plan; no-trade/zero-loss metrics are null/insufficient evidence rather than profitability claims. No synchronized multi-asset portfolio claim from independent-asset runs.
