import json, subprocess, sys
from pathlib import Path
OUT=Path(__file__).resolve().parent
ROOT=Path(r'E:\coding\code\Trade\MiroFish')
result=json.loads((OUT/'result.json').read_text(encoding='utf-8'))
result['attempt_notes']=['First root attempt had harness import-path error; corrected by adding repository root to sys.path.','First HTTP attempt required absent requests; harness corrected to use already-installed httpx. Repository sources untouched.']
result['runs'].extend([
 {'mode':'root-retry','command':[sys.executable,str(OUT/'run_runtime.py'),'root'],'cwd':r'E:\coding\code\Trade\MiroFish\backend','exit_code':1,'log':str(OUT/'root-retry.log'),'result':'28 run, 27 pass, 1 Windows symlink rejection failure'},
 {'mode':'http-retry','command':[sys.executable,str(OUT/'run_runtime.py'),'http'],'cwd':r'E:\coding\code\Trade\MiroFish\backend','exit_code':0,'log':str(OUT/'http-retry.log'),'result':'15 actual loopback HTTP requests pass; 2 deterministic fake provider calls; shutdown confirmed'},
 {'mode':'frontend-build','command':['npm.cmd','run','build'],'cwd':r'E:\coding\code\Trade\mirofish-evidence\frontend-build','exit_code':0,'log':str(OUT/'frontend-build.log'),'result':'built in44.72s; mixed static/dynamic import warning and >500kB JS chunk warning'}])
for run in result['runs']:
    if run['mode'] in ('root-retry','http-retry'):
        run['cwd']=r'C:\Users\hp\Documents\ChatGPT\Trading'
result['node']='v24.18.1'; result['npm']='11.16.0'
result['git_status_after']=subprocess.check_output(['git','-C',str(ROOT),'status','--short'],text=True)
result['scope']={'dotenv':'load_dotenv replaced with no-op before application import; no private .env read','network':'socket.connect permits loopback only in Python harness','real':['Flask app factory and WSGI HTTP server','TXT Markdown Unicode and PDF parsers','OpenAI SDK HTTP serialization and response parsing','ontology normalization','local JSON/file persistence','reset/delete local project lifecycle','server shutdown'],'fake':['LLM provider responses from deterministic local HTTP fixture'],'not_tested':['real LLM inference','Zep Cloud graph creation/ingestion/query/deletion','OASIS/CAMEL simulation process','full browser UI flow'],'repository_source_changes':False}
(OUT/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
summary='''# MiroFish runtime verification

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

Reproduce from backend cwd with the evidence venv Python: `run_runtime.py backend`, `run_runtime.py root`, `run_runtime.py http`. Root exits1 for the recorded Windows failure. `run_runtime.py` without mode reruns all three. Frontend command: `npm.cmd run build` in E:\\coding\\code\\Trade\\mirofish-evidence\\frontend-build.
'''
(OUT/'RESULT.md').write_text(summary,encoding='utf-8')
assert result['git_status_after']==''
assert json.loads((OUT/'http-result.json').read_text(encoding='utf-8'))['status']=='passed'
print('Evidence finalized; clean repository; fresh backend129pass/root27pass1failure/HTTP15pass/frontend build0')
