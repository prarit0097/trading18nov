# MiroFish runtime verification

Pinned commit: `7657031ac01184afe2cb220f5ee3545573b5e843`. Git status clean before and after. No repository source edits. Windows 11; Python 3.12.3; Node 24.18.1; npm 11.16.0. Exact commands, versions and logs are in result.json; full Python versions in pip-freeze.txt.

| Check | Fresh result |
|---|---|
| Backend pytest | **129 passed**, 1 harmless already-imported-module rewrite warning; 31.04s pytest time |
| Root unittest | **28 run: 27 pass, 1 failure**; Windows symlink count-file validation, test_local_star_history.py:440 |
| Actual Flask/Werkzeug HTTP lifecycle | **15 requests passed**, 2 local fake provider calls; server shutdown confirmed |
| Frontend isolated production build | **Exit 0**, 44.72s; static/dynamic import and 520.18kB JS chunk warnings |

The HTTP run starts the real app on an ephemeral loopback TCP port, validates health, empty project list, missing project and upload validation, uploads TXT/Markdown/PDF in one multipart request, verifies Unicode and all three parsed source sentinels reach the real OntologyGenerator and OpenAI SDK, then checks ontology normalization, persisted JSON state, reset, delete and 404 after deletion. A deterministic local OpenAI-compatible HTTP server supplies the model response. A second fixture returns HTTP401; the app returns502 without exposing its private fake body, persists failed project state, and supports deletion. Local project list is empty after cleanup. http-result.json records all15 responses.

These are real local HTTP/parser/SDK/application/persistence checks with a **fake model boundary**. No live model inference or Zep operation ran. OASIS/CAMEL distributions are absent from this minimal environment; full synthetic social simulation and reports over a live graph remain unverified. No private .env read: dotenv loading disabled before application imports. Python socket.connect blocked non-loopback connections. Fixture uploads, logs, and temp files stay under this artifact directory.

The root failure reproduces the previously documented Windows issue: the symlink file does not raise StarHistoryError. It is not an application HTTP failure and was not fixed in this runtime-only task. Backend tests remain offline mocks/fakes. Frontend compilation does not establish browser interaction correctness.

Initial root/HTTP harness attempts failed due to harness sys.path and an absent requests package. The harness was corrected to include repository root and use installed httpx; original failed logs and successful retry logs are retained. No dependency installation was required.

Reproduce from backend cwd with the evidence venv Python: `run_runtime.py backend`, `run_runtime.py root`, `run_runtime.py http`. Root exits1 for the recorded Windows failure. `run_runtime.py` without mode reruns all three. Frontend command: `npm.cmd run build` in E:\coding\code\Trade\mirofish-evidence\frontend-build.
