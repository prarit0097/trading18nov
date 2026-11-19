from pathlib import Path
import os,sys,subprocess,json,hashlib,shutil
b=Path(r'E:\coding\code\Trade');r=b/'TradingAgents';e=b/'tradingagent-evidence';td=e/'offline-tests';td.mkdir(exist_ok=True)
paths=['tests/test_symbols.py','tests/test_safe_ticker_component.py','tests/test_env_overrides.py','tests/test_get_scrubbed.py'];records=[]
for name in paths:
 p=td/Path(name).name;shutil.copyfile(r/name,p);records.append({'source':name,'copy':p.relative_to(b).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(td/'pytest.ini').write_text('[pytest]\naddopts = -p no:cacheprovider\nmarkers =\n    unit: upstream unit tests\n',encoding='utf-8')
(td/'conftest.py').write_text('''import socket,pytest\n@pytest.fixture(autouse=True)\ndef no_network(monkeypatch):\n def refuse(*a,**kw):raise AssertionError("network disabled in documentation verification")\n monkeypatch.setattr(socket.socket,"connect",refuse)\n monkeypatch.setattr(socket.socket,"connect_ex",refuse)\n monkeypatch.setattr(socket,"getaddrinfo",refuse)\n''',encoding='utf-8')
# Empty local dotenv files bound the package's upward dotenv search; no personal files/keys read.
for name in ['.env','.env.enterprise']:(e/name).write_text('',encoding='utf-8')
env={k:v for k,v in os.environ.items() if not k.startswith('TRADINGAGENTS_')};env['PYTHONPATH']=str(r);env['PYTHONDONTWRITEBYTECODE']='1';env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1';env['PYTHONIOENCODING']='utf-8'
for k,v in [('TRADINGAGENTS_RESULTS_DIR','test-state/logs'),('TRADINGAGENTS_CACHE_DIR','test-state/cache'),('TRADINGAGENTS_MEMORY_LOG_PATH','test-state/memory.md')]:env[k]=str(e/v)
cmd=[sys.executable,'-m','pytest','-q','-c',str(td/'pytest.ini'),*[str(td/Path(x).name) for x in paths]]
p=subprocess.run(cmd,cwd=e,env=env,capture_output=True,text=True,encoding='utf-8');(e/'offline-tests.txt').write_text(p.stdout+'\nSTDERR:\n'+p.stderr,encoding='utf-8')
(e/'offline-test-manifest.json').write_text(json.dumps({'command':cmd,'exit_code':p.returncode,'files':records,'scope':'Unmodified copies of4upstream testfiles; actual source imports. Full conftest bypassed (requires LangChain/CLI dependencies unavailable here). Local network blocking fixture, isolated dotenv and appstate paths; no source rewrites or dependency stubs.'},indent=2),encoding='utf-8')
print(p.stdout[-3500:]);print(p.stderr[-1000:]);print('EXIT',p.returncode)
