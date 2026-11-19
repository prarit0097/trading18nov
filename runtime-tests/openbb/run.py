import os, sys, subprocess, json, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
HOME=ROOT/'home'; HOME.mkdir(exist_ok=True)
env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC','PATHEXT','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE'}}
env.update(USERPROFILE=str(HOME),HOME=str(HOME),HOMEDRIVE=HOME.drive,HOMEPATH=str(HOME)[2:],OPENBB_DEV_MODE='true',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
env['PATH']=str(ROOT/'venv/Scripts')+os.pathsep+env.get('PATH','')
command=[str(ROOT/'venv/Scripts/python.exe'), *sys.argv[2:]]
started=time.time()
p=subprocess.run(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
name=sys.argv[1]
(ROOT/f'{name}.log').write_text(p.stdout,encoding='utf-8')
record={'command':command,'cwd':str(ROOT),'exit_code':p.returncode,'seconds':round(time.time()-started,2),'isolation':'whitelisted OS env, empty HOME/USERPROFILE, no dotenv credentials; DEV_MODE true'}
(ROOT/f'{name}.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record)); print(p.stdout[-10000:]); sys.exit(p.returncode)
