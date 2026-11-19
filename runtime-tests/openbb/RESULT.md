# OpenBB local runtime qualification

Result: PASS for bounded local core runtime. 82 repository tests passed, 0 failed, 0 skipped; installed SDK/registry initialization and four local API endpoints passed. This expands the previous22 copied offline tests; it does not qualify live providers.

Source: E:\coding\code\Trade\OpenBB, pinned e43353a82815ff9ba56ad1b7ad47c32729dcf314. Git status stayed clean. No tracked source changes.

Environment: Windows11, Python3.13.5, isolated venv, source-built openbb-core2.0.1; resolved packages saved packages.txt. Declared dependency install succeeded; pip check reports no broken requirements. Exact suite/smoke commands, duration and exit codes are in core-tests.json and smoke.json; raw logs and JUnit XML preserved. Install commands and statuses are in result.json; install.log contains dependency resolution and wheel hash.

The runner starts children from the artifact directory with a whitelist of OS variables, an empty artifact-local HOME/USERPROFILE, no inherited provider secrets, and DEV_MODE=true. Private .env/config files were neither inspected nor loaded. SDK generated files/settings remain inside the artifact venv/home. No broker or paid calls.

Runtime checks: import `from openbb import obb`; initialize Registry; read version/reference; assemble the real FastAPI app; enter ASGI lifespan; GET /openapi.json, /api/v1/system, /api/v1/coverage/providers, /api/v1/coverage/commands, /api/v1/coverage/command_model; assert200 and404 for nonexistent route. Outbound socket connections are denied in smoke.py; loopback permitted for Windows asyncio self-pipe. API coverage is empty because no providers/extensions are installed, as expected.

Repository suite: provider registry, registry mapping, query executor; assembled REST app; SDK app factory; generated Python SDK syntax/import/signatures/delegation using actual ruff; command-output extension callbacks through real CommandRunner and FastAPI dispatch. Tests use upstream deterministic fake providers/stubs; none is a live market-data integration test.

Retained setup attempts: smoke-premature.* ran before package install completed (ModuleNotFoundError); smoke-loopback-blocked.* overblocked Windows asyncio's loopback self-pipe; core-tests-no-ruff-path.* passed59/skipped23 until venv Scripts was added to PATH. Final smoke exit0 and suite82/82passed. These were harness setup issues, not demonstrated OpenBB bugs.

Limits: no full provider install, vendor endpoints, pandas/charting extras, CLI launcher, MCP, Workspace deployment, authentication configuration, real uvicorn socket serving or live broker tested. Minimal install warns optional email-validator is absent and fields fall back to strings; Starlette warns httpx TestClient is deprecated. Neither warning failed checks. Source wheel shipped metadata for unavailable extensions, which SDK auto-build removed only from installed artifact copy.

Latest verified quota:69% consumed/31% remaining in300-minute window. No further broadening needed for this bounded qualification.
