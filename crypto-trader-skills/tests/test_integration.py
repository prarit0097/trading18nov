import contextlib,io,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from crypto_skills.cli import main,report
from crypto_skills.core import Workspace
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
NOW='2026-11-17T12:00:00Z'

class IntegrationTests(unittest.TestCase):
 def test_report_includes_research_qualification_without_calling_it_trade_approval(self):
  with tempfile.TemporaryDirectory() as tmp:
   w=Workspace(tmp);w.write('qualification',{'status':'rejected','orders_submitted':0})
   obj=report(SimpleNamespace(workspace=tmp,now=NOW))
   self.assertEqual(obj['data']['status'],'inspection')
   self.assertEqual(obj['data']['results']['qualification']['status'],'rejected')
 def command(self,*args):
  result=subprocess.run([sys.executable,*map(str,args)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
  self.assertEqual(result.returncode,0,result.stderr+result.stdout)
  return json.loads(result.stdout)

 def test_separate_skill_wrappers_share_one_workspace(self):
  with tempfile.TemporaryDirectory() as tmp:
   common=['--workspace',tmp,'--now',NOW]
   self.command('skills/crypto-workflow/scripts/workflow.py','init',*common,'--input','examples/paper-config.json')
   for skill,extra in [('market',['--input','examples/market.json']),('news',['--input','examples/news.json']),('entry',[]),('exit',[]),('size',[]),('risk',[]),('backtest',[]),('timemachine',['--replays','40']),('world',['--agents','50']),('paper',['submit']),('report',[])]:
    with self.subTest(skill=skill):
     obj=self.command(f'skills/crypto-{skill}/scripts/{skill}.py',*extra,*common)
     self.assertIn('digest',obj)
   w=Workspace(tmp)
   self.assertTrue(w.read('risk')['data']['approved'])
   self.assertEqual(len(w.read('ledger')['data']['orders']),1)
   self.assertEqual(w.read('simulation')['inputs']['plan'],w.read('plan')['digest'])

 def test_complete_demo_and_independent_skill_handoffs(self):
  with tempfile.TemporaryDirectory() as tmp:
   summary=self.command('run.py','demo','--workspace',tmp)
   self.assertEqual(summary['data']['live_orders_submitted'],0)
   w=Workspace(tmp)
   for name in ('config','market','news','proposal','plan','sizing','risk','ledger','portfolio','orders','backtest','simulation','world','report'):
    self.assertEqual(w.read(name)['kind'],name)
   self.assertIn('observed candles',(Path(tmp)/'chart.svg').read_text(encoding='utf-8'))
   sim=w.read('simulation')['data']['metrics'];world=w.read('world')['data']['metrics']
   self.assertEqual(sim['replays'],10000)
   self.assertEqual(sim['win_count']+sim['loss_count']+sim['flat_count'],10000)
   self.assertEqual(world['participant_count'],10000)
   self.assertGreater(world['matched_trades'],0)
   self.assertEqual(world['initial_cash_units'],world['final_cash_units'])
   self.assertEqual(world['initial_inventory_lots'],world['final_inventory_lots'])
   self.assertTrue(world['all_balances_nonnegative'])
   ledger=w.read('ledger')
   inspected=self.command('run.py','status','--workspace',tmp)
   self.assertNotIn('previous_ledger',inspected['data']['artifacts']['ledger']['changed_inputs'])
   self.command('skills/crypto-paper/scripts/paper.py','submit','--workspace',tmp,'--now',NOW)
   self.assertEqual(w.read('ledger')['digest'],ledger['digest'])
   report=self.command('skills/crypto-report/scripts/report.py','--workspace',tmp,'--now',NOW)
   self.assertEqual(report['data']['status'],'inspection')
   self.command('skills/crypto-paper/scripts/paper.py','close','--price','101000','--workspace',tmp,'--now',NOW)
   closed=w.read('ledger')
   self.assertEqual(len(closed['data']['positions']),0)
   self.assertEqual(len(closed['data']['orders']),2)
   self.command('skills/crypto-paper/scripts/paper.py','close','--price','101000','--workspace',tmp,'--now',NOW)
   self.assertEqual(w.read('ledger')['digest'],closed['digest'])

 def test_pipeline_waiting_exit_is_not_success(self):
  market={'kind':'market','data':{'health':{'valid':True}}}
  waiting={'kind':'proposal','data':{'status':'waiting','reasons':['No trigger']}}
  with patch('crypto_skills.market.run',return_value=market),patch('crypto_skills.trade.run',return_value=waiting),contextlib.redirect_stdout(io.StringIO()) as stream:
   code=main(['pipeline','--workspace','.','--input','dummy.json'])
  self.assertEqual(code,1)
  self.assertEqual(json.loads(stream.getvalue())['data']['status'],'waiting')

 def test_report_labels_synthetic_chart_and_discards_chart_after_failed_refresh(self):
  with tempfile.TemporaryDirectory() as tmp:
   self.command('run.py','init','--workspace',tmp,'--input','examples/paper-config.json','--now',NOW)
   self.command('run.py','market','--workspace',tmp,'--input','examples/market.json','--now',NOW)
   args=SimpleNamespace(workspace=tmp,now=NOW)
   first=report(args)
   path=Path(tmp)/'chart.svg'
   self.assertEqual(first['data']['chart'],'chart.svg')
   self.assertIn('Synthetic',path.read_text(encoding='utf-8'))
   Workspace(tmp).write('market',{'health':{'valid':False},'error':'Rejected refresh'},now=NOW)
   second=report(args)
   self.assertFalse(path.exists())
   self.assertIsNone(second['data']['chart'])
   self.assertEqual(second['data']['results']['market']['error'],'Rejected refresh')

if __name__=='__main__':unittest.main()
