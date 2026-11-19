import tempfile,unittest,copy
from decimal import Decimal
from pathlib import Path
from crypto_skills.core import Workspace,SkillError,digest
from tests.test_research import market,config
from crypto_skills import validation as v
from unittest.mock import patch

def result(pnl='10',count=20,drawdown='5'):
    return {'metrics':{'net_pnl':pnl,'trade_count':count,'max_drawdown_quote':drawdown,'initial_cash':'10000','total_fees':'1'},
            'trades':[{'net_pnl':str(Decimal(pnl)/count),'entry_price':'100','quantity':'1','exit_time':'2026-01-01T00:00:00Z'} for _ in range(count)]}

class ValidationTests(unittest.TestCase):
 def test_split_is_disjoint_and_future_changes_do_not_touch_train(self):
  m=market([(100,101,99,100)]*48)
  a=v.partition(m);self.assertEqual([len(a[x]['bars']) for x in ('train','validation','test')],[24,12,12])
  self.assertLess(a['train']['bars'][-1]['time'],a['validation']['bars'][0]['time'])
  changed=copy.deepcopy(m);changed['bars'][-1]['close']='500'
  self.assertEqual(a['train'],v.partition(changed)['train'])
 def test_training_selection_never_uses_no_trade_as_an_edge(self):
  chosen=v.choose({'no_trades':[result('0',0)]*3,'loss':[result('-5')]*3})
  self.assertFalse(chosen['training_pass'])
  self.assertEqual(chosen['id'],'no_trades')
  chosen=v.choose({'b':[result('10')]*3,'a':[result('10')]*3})
  self.assertEqual(chosen['id'],'a');self.assertTrue(chosen['training_pass'])
 def test_metrics_undefined_ratios_are_null(self):
  r=result('0',0);m=v.metrics(r)
  self.assertIsNone(m['profit_factor']);self.assertIsNone(m['net_expectancy']);self.assertIsNone(m['win_rate'])
  self.assertEqual(v.metrics(result())['win_rate'],'1')
 def test_validation_requires_profit_count_baseline_and_drawdown(self):
  base=[result('0',20,'10')]*3
  self.assertTrue(v.comparison([result('10')]*3,base,20))
  self.assertFalse(v.comparison([result('-1')]*3,base,20))
  self.assertFalse(v.comparison([result('10',1)]*3,base,20))
  self.assertFalse(v.comparison([result('10',20,'11')]*3,base,20))
 def test_bootstrap_is_reproducible_and_keeps_loss(self):
  series=['-2']*15
  a=v.block_interval(series);self.assertEqual(a,v.block_interval(series))
  self.assertEqual(Decimal(a['lower']),Decimal('-2'));self.assertEqual(a['observations'],15)
 def test_holdout_registry_rejects_new_fingerprint_on_overlapping_dates(self):
  with tempfile.TemporaryDirectory() as t:
   self.assertFalse(v.reserve_holdout(t,'2026-01-01','2026-01-16','a'))
   self.assertFalse(v.reserve_holdout(t,'2026-01-01','2026-01-16','a'))
   self.assertTrue(v.reserve_holdout(t,'2026-01-10','2026-01-25','b'))
   self.assertFalse(v.reserve_holdout(t,'2026-01-25','2026-02-10','c'))
 def test_stress_failure_and_reused_holdout_cannot_qualify(self):
  good=[result('10')]*3;base=[result('0')]*3
  self.assertFalse(v.promotion(True,True,good,base,[result('-1')]*3,{'lower':'1'},False))
  self.assertFalse(v.promotion(True,True,good,base,good,{'lower':'1'},True))
  self.assertFalse(v.promotion(True,True,good,base,good,{'lower':'-1'},False))
  self.assertTrue(v.promotion(True,True,good,base,good,{'lower':'1'},False))
 def test_earlier_training_dates_are_also_seen_for_later_experiments(self):
  with tempfile.TemporaryDirectory() as t:
   v.reserve_holdout(t,'2026-10-30','2026-11-14','first',seen_start='2026-09-15')
   self.assertTrue(v.reserve_holdout(t,'2026-09-29','2026-10-14','second',seen_start='2026-08-15'))
 def test_download_date_and_trial_spec_are_pinned(self):
  with self.assertRaises(SkillError):v.specification('2026-11-14T00:05:00Z',60)
  s=v.specification('2026-11-14T00:00:00Z',60)
  self.assertEqual(len(s['variants']),4);self.assertEqual(s['bars_per_asset'],17280)
 def test_completed_result_must_match_fingerprint(self):
  with tempfile.TemporaryDirectory() as t:
   w=Workspace(t);w.write('qualification',{'fingerprint':'old','status':'rejected'})
   with self.assertRaises(SkillError):v.completed(w,'new')
   self.assertEqual(v.completed(w,'old')['data']['status'],'rejected')
   with self.assertRaises(SkillError):v.completed(w,'old',{'history':'new-digest'})

 def fake_api(self,path,params):
  if path.endswith('exchangeInfo'):
   s=params['symbol'];return {'symbols':[{'symbol':s,'baseAsset':s[:-4],'quoteAsset':'USDT','filters':[
    {'filterType':'LOT_SIZE','stepSize':'0.001'},{'filterType':'PRICE_FILTER','tickSize':'0.01'},
    {'filterType':'NOTIONAL','minNotional':'5'}]}]}
  return [[params['startTime']+i*300000,'100','101','99','100','10',params['startTime']+i*300000+299999] for i in range(params['limit'])]

 def test_download_resume_and_full_frozen_no_trade_experiment(self):
  with tempfile.TemporaryDirectory() as t,patch.object(v,'_get_json',side_effect=self.fake_api),patch.object(v.time,'sleep'):
   with patch('builtins.print'):v.download(t,'2026-01-13T00:00:00Z',12)
   w=Workspace(t);self.assertEqual(len(w.read('history_btcusdt')['data']['market']['bars']),3456)
   with patch.object(v,'_get_json',side_effect=AssertionError('Unexpected repeat network')):
    v.download(t,'2026-01-13T00:00:00Z',12)
   with patch.object(v,'reserve_holdout',return_value=False):
    a=v.evaluate(t)
    self.assertEqual(a['data']['status'],'rejected')
    self.assertFalse(a['data']['validation_pass'])
    self.assertEqual(a['digest'],v.evaluate(t)['digest'])
   spec=w.read('experiment_spec')['data'];spec['variants']['baseline']['lookback']=2
   w.write('experiment_spec',spec)
   with self.assertRaises(SkillError):v.evaluate(t)

 def test_missing_historical_candle_fails_instead_of_silent_gap(self):
  def bad(path,params):
   obj=self.fake_api(path,params)
   if isinstance(obj,list):obj[0][0]+=300000
   return obj
  with tempfile.TemporaryDirectory() as t,patch.object(v,'_get_json',side_effect=bad),patch.object(v.time,'sleep'):
   with self.assertRaises(SkillError):v.download(t,'2026-01-13T00:00:00Z',12)

if __name__=='__main__':unittest.main()
