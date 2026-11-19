from pathlib import Path
import os,sys,subprocess,json,copy,hashlib,datetime
b=Path(r'E:\coding\code\Trade');repo=b/'day-trader-skill';out=b/'runtime-tests/daytrader';work=out/'historical-nvda';(work/'trader').mkdir(parents=True,exist_ok=True)
old=Path((b/'nvda-timemachine/latest-run.txt').read_text().strip());raw=old/'NVDA-60d5m.json'
cfg=json.loads((repo/'trader-budget/config.example.json').read_text());cfg.pop('sec_user_agent',None)
(work/'trader/config.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
now='2026-11-12 10:00';env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8');records=[]
def run(label,path,args,expected=0):
 cmd=[sys.executable,str(repo/path),*args]
 start=datetime.datetime.now(datetime.timezone.utc).isoformat()
 p=subprocess.run(cmd,cwd=work,env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
 (out/(label+'.stdout.txt')).write_text(p.stdout,encoding='utf-8');(out/(label+'.stderr.txt')).write_text(p.stderr,encoding='utf-8')
 records.append({'label':label,'command':cmd,'cwd':str(work),'started':start,'exit_code':p.returncode,'expected_exit':expected})
 (out/'smoke-commands.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
 assert p.returncode==expected,(label,p.stderr[-1500:],p.stdout[-1500:])
 print(label,'PASS',flush=True)
 return json.loads(p.stdout)
entry=run('01-entry','trader-entry/entry.py',['check','NVDA','--offline',str(raw),'--now',now,'--write','--json'])
assert entry['status']=='triggered' and entry['opening_range']['bars']==3
plan=run('02-plan','trader-exit/exit.py',['plan','--now',now,'--write','--json'])
price=json.loads((work/'trader/plan.json').read_text())['entry']
(work/'trader/prices.json').write_text(json.dumps({'as_of':'2026-11-12T15:00:00Z','prices':{'NVDA':price},'detail':{'NVDA':{'time':'2026-11-12T15:00:00Z','source':'captured historical 09:55 bar close, NOT live quote'}}}),encoding='utf-8')
orders=run('03-size','trader-budget/size.py',['--now',now,'--write','--json'])
risk=run('04-risk','trader-risk/check.py',['--now',now,'--json'])
assert risk['block']==0
tickets=run('05-ticket','trader-broker/ticket.py',['show','--now',now,'--json'])
assert any(t['ready'] for t in tickets)
bad=json.loads((work/'trader/orders.json').read_text());seq=bad['orders'] if isinstance(bad,dict) else bad;seq[0]['qty']=10000
(work/'trader/oversized-orders.json').write_text(json.dumps(bad),encoding='utf-8')
blocked=run('06-oversized-risk','trader-risk/check.py',['--orders','trader/oversized-orders.json','--out','trader/state/oversized-risk.json','--now',now,'--json'],1)
assert blocked['block']>0
assert not (work/'trader/state/broker.json').exists()
result={'status':'PASS','mode':'offline historical-data CLI integration','commit':subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip(),'stages_passed':6,'historical_session':'2026-11-12','clock_pinned_et':now,'fixture_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'entry_status':entry['status'],'risk_block_count':risk['block'],'oversized_block_count':blocked['block'],'ticket_ready_count':sum(t['ready'] for t in tickets),'orders_approved':0,'orders_submitted':0,'limits':['Historical bar close substituted as deterministic test quote; not a live execution quote','Example $5000 budget is fictional','No broker connector, fills, live feed or P&L test']}
(out/'smoke-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
