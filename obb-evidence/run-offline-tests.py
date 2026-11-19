from pathlib import Path
import subprocess,sys,os,json,hashlib,shutil
b=Path(r'E:\coding\code\Trade');r=b/'OpenBB';e=b/'obb-evidence';td=e/'offline-tests';td.mkdir(exist_ok=True)
paths=['openbb_platform/core/tests/app/test_utils_optional.py','openbb_platform/core/tests/app/model/abstract/test_singleton.py','openbb_platform/core/tests/app/model/abstract/test_warning.py']
records=[]
for p in paths:
 target=td/Path(p).name;shutil.copyfile(r/p,target);records.append({'source':p,'copy':target.relative_to(b).as_posix(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
(td/'pytest.ini').write_text('[pytest]\naddopts = -p no:cacheprovider\n',encoding='utf-8')
env=os.environ.copy();env['PYTHONPATH']=str(r/'openbb_platform/core');env['PYTHONDONTWRITEBYTECODE']='1';env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1';env['PYTHONIOENCODING']='utf-8'
cmd=[sys.executable,'-m','pytest','-q','-c',str(td/'pytest.ini'),*[str(td/Path(p).name) for p in paths]]
p=subprocess.run(cmd,cwd=e,env=env,capture_output=True,text=True,encoding='utf-8')
(e/'offline-tests.txt').write_text(p.stdout+'\nSTDERR:\n'+p.stderr,encoding='utf-8')
(e/'offline-test-manifest.json').write_text(json.dumps({'command':cmd,'exit_code':p.returncode,'files':records,'scope':'Unmodified source test copies; original repository conftest bypassed to avoid unavailable full-install dependencies; actual core source imported via PYTHONPATH; no stubs or live provider calls.'},indent=2),encoding='utf-8')
print(p.stdout[-4000:]);print(p.stderr[-1000:]);print('EXIT',p.returncode)
