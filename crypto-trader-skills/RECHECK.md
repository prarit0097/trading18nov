# Recheck: 2026-11-17

Reviewed installed paths, isolated Python, JSON lineage/accounting, entry/exit/risk, research and public-feed parsing. Scope is one local paper/research workspace with separate skill processes; this is not production exchange qualification.

## Problems reproduced and repaired

1. **Discovery registration:** only earlier Codex-home links existed. Added all 12 links at the documented user root `C:\Users\hp\.agents\skills`. This matches this host's current user-skill root. Existing unrelated skills and compatibility links were preserved. [Official discovery and symlink guidance](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).
2. **UTF-16 XML declarations:** byte matching caught UTF-8 DTDs but accepted UTF-16 DTD/entity declarations and expanded an internal entity. Added parser-level DOCTYPE rejection. Regression covers UTF-16 with BOM, little endian and big endian; normal UTF-16 RSS remains accepted.
3. **Missing market snapshot time:** an explicit null `as_of` could use the optional clock helper's current-time fallback. Trade validation now requires an explicit string timestamp. A frozen-clock regression demonstrates rejection.
4. **Initialization race:** `init` checked and wrote config without the single-writer lock. It now holds that lock across the existing-config check and write; a regression attempts a second writer during config creation.
5. **False ledger warning:** status treated the previous journal digest as a missing current artifact. It now recognizes `previous_ledger` as a historical pointer. Actual market/config/account input changes are still checked.

The four code repairs were preceded by failing regression checks, followed by passing targeted checks. Added an ETH spot entry → plan → size → risk → paper buy → close accounting test as well.

## Fresh evidence

Final result: **67 tests passed** in 11.442 seconds. All 12 installed wrappers and skill validators passed, along with compilation and the installed-path 10,000-replay/10,000-participant demo.

See [final test output](verification/recheck/unit-tests.txt) and [machine-readable checks](verification/recheck/checks.json). The check run includes the isolated interpreter, all 12 discovered-folder wrapper entrypoints from an unrelated directory, official skill metadata validation, source hashes and compilation. It also runs a fresh 10,000-replay/10,000-participant synthetic demo through the newly registered workflow path; [demo summary](verification/recheck/demo-summary.json).

The prior 63-test build/setup logs are historical evidence. Use this recheck's newer log for current code.

## Remaining boundaries

No app restart or observed skill-selector refresh occurred during this check. Disk registrations, targets, references and actual scripts are verified; restart Codex if its selector remains stale, as the official guidance describes. No new public network availability/latency benchmark was taken; previous public smoke files retain their original timestamps.

Supported mode remains spot paper/research. Perpetual execution/backtest/replay, automatic protective orders, continuous news/WebSocket collection, actual MiroFish integration and a calibrated forecast are outside the implemented scope. The synthetic world is a random finite-cash batch market. Passing accounting/security tests does not validate profitability.
