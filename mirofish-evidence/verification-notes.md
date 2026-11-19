## Verification: kya actually check hua

Source snapshot ka inventory, archive evidence, Python syntax, backend unit tests, frontend build aur document-reference consistency alag checks hain. Kisi ek ka pass hona baaki checks ka substitute nahi.

| Check | Actual result | Practical meaning |
|---|---|---|
| Git source identity | HEAD `7657031ac01184afe2cb220f5ee3545573b5e843` | Analysis pinned snapshot par hai |
| Tracked source inventory | 128 files, per-file SHA-256 and line counts retained | Document file coverage mechanically inspect ho sakti hai |
| Python AST parse | 62 files parsed, 0 errors | Source syntax inspected; runtime dependencies/behavior prove nahi |
| Backend pytest | **129 passed in 14.56s**, Python 3.12, Windows | Shipped offline tests pass in isolated minimal test environment |
| Root unittest | **28 run: 27 pass, 1 failure**, Python 3.12; same failure on 3.13 | Star-history helper suite is not fully passing on this Windows host |
| Frontend install/build | npm ci then npm run build exit 0, Node 24.18.1 | Locked frontend compiles; no browser end-to-end click test |
| Build warning | JS chunk 520.18 kB; >500 kB minified warning | Build succeeded with warning, not a runtime performance benchmark |
| REA archive inspection | complete-within-substeps, no integrity contradictions | ZIP inventory evidence, not application semantics |
| Document audit | Saved final check in `document-validation.json` | References, API/file inclusion, source hashes and document structure checked |

Commands/logs: `backend-tests.txt`, `root-tests-py312.txt`, `root-tests.txt`, `frontend-install.txt`, `frontend-build.txt`, `test-environment.txt`, `verification-manifest.json`. First frontend command was accidentally issued from evidence root, which has no package lock; it failed before installation. Correcting working directory to the isolated frontend copy produced the recorded successful build. No repository source repair was made.

### Windows failure ka reproduced cause

Failure `test_count_file_rejects_symlinks_malformed_and_extreme_values` ka last symlink assertion hai (`tests/test_local_star_history.py:414`, `tests/test_local_star_history.py:440`). `load_star_count_file` opens with O_RDONLY and conditionally adds O_NOFOLLOW (`scripts/star_history.py:510`). Windows Python mein `os.O_NOFOLLOW` absent tha; os.open followed the link and fstat saw a normal target file. Reproduction mein is_symlink=true file se count **0** return hua instead of raising StarHistoryError. Evidence `windows-symlink-reproduction.json`. Thus exact finding count-file symlink rejection is platform-dependent; malformed/negative/oversize cases ko failure ka cause nahi bola gaya. CI star-history workflow Ubuntu par chalta hai, so this Windows observation alone does not prove that CI fails. User asked analysis, isliye implementation untouched rakhi gayi.

### Test boundaries

Backend test filenames cover ontology types/attributes/API failures, JSON LLM fallbacks, OpenAI response parameter compatibility, profile normalization and per-platform file contracts, zero-entity prepare failure, report tool-result sanitization, Zep Cloud SDK contracts, graph lifecycle, edge pagination, retry/client, memory-update drain/failure behavior, report/simulation ingestion barriers and manual-validation script behavior. Actual assertions mostly mocks/fakes/local temporary files use karti hain; passing them real credentials ya external service availability validate nahi karta. Full list source appendix mein included hai.

Offline checks ke liye Python 3.12 venv evidence directory mein banayi aur Flask/OpenAI/Zep/parser/test dependencies install ki. Entire heavy OASIS/CAMEL runtime environment install nahi kiya; test pass ko frozen production environment ka full validation claim nahi. Backend tests real provider requests ke replacement fakes use karte hain. Config placeholders ko valid key treat karke API run nahi ki gayi. No actual private `.env` read/printed, no paid LLM inference, no graph creation/deletion on Zep Cloud, no GitHub write, no Docker launch aur no hosted deployment hua.

Manual `backend/scripts/validate_zep_cloud_integration.py` real Cloud validation script deliberately automated suite se separate hai. It captures caller key before config dotenv override, exercises temporal graph updates/retrieval/memory ingestion and cleans graph unless keep-graph supplied; if drain uncertain, retains graph rather than race-delete. Is audit mein is script ka **live mode nahi** chala. `backend/scripts/test_profile_format.py` bhi supplemental developer diagnostic hai, passing backend pytest ka part automatically nahi maana. Source: `backend/scripts/validate_zep_cloud_integration.py:1`, `backend/scripts/test_profile_format.py:1`.

## Source-grounded limitations aur unknowns

1. **Prediction claim vs validation:** seed-conditioned personas, synthetic social actions aur generated narrative code mein implemented hain; arbitrary future prediction ki measured accuracy/calibration independent ground-truth evaluation se establish nahi hoti. README vision, report prompt language aur a particular generated report ko observed real-world truth nahi kehna.
2. **External dependencies:** LLM provider and Zep Cloud are operational dependencies; source alone provider uptime, billing, data retention, rate limits or internal extraction correctness guarantee nahi karta. OASIS core execution third-party implementation hai.
3. **Persistence boundaries:** durable JSON/text/SQLite coexist with process-local task state, locks/read leases/runner handles. Restart se every background operation resume hona established behavior nahi; detailed service sections distinguish metadata recovery from live environment recovery.
4. **Input/prompt quality:** PDF text extraction and generated ontology/personas inherit source omissions and model errors. Scanned PDF OCR path this parser mein nahi; simulation agents are synthetic. No fixed monetary cost or deterministic run duration can be derived without actual provider usage.
5. **Runtime mismatches:** detailed notes flag single-platform logging gaps, metadata/counter mismatches, stale client routes and generated configuration fields not consumed by scripts. These are source observations, not all independently reproduced end-to-end failures.
6. **Deployment boundary:** development Flask/Vite launch, broad CORS, no app login/tenant ownership and default secret require attention if serving beyond a local controlled environment. Hosted mirofish.ai may have protections not included here; its architecture was not reverse engineered.
7. **Completeness boundary:** every tracked file and route is catalogued; vendor source, closed deployment components, full Git history, remote datasets, hidden tests and unexecuted race schedules remain outside evidence. This document does not claim zero defects or prove that nothing can ever go wrong.

## Short glossary

| Term | Is repo mein meaning |
|---|---|
| Seed material | User-uploaded documents from which scenario context is extracted |
| Ontology | Allowed entity classes, edge classes and their fields; generated schema |
| Entity/node | Person/organization/other typed object in Zep graph |
| Edge/fact | Relationship and text fact connecting graph nodes |
| Episode | Text/activity record submitted into graph memory ingestion |
| Persona/profile | Graph-context-conditioned synthetic agent identity and behavioral description |
| Round | Configured time step, not a wall-clock minute or model training epoch |
| GraphRAG | Graph retrieval context supplied to generation; not proof all retrieved facts are true |
| ReportAgent | Tool-using LLM reporting loop over scenario graph and optional agent interviews |
| IPC | Local command/response JSON files between Flask backend and simulation process |
| Barrier/drain | Wait for producer shutdown and pending graph ingestion before permitting report/destructive lifecycle changes |

