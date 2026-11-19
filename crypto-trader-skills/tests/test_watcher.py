import copy,json,tempfile,unittest
from pathlib import Path
from decimal import Decimal
from argparse import Namespace
from unittest.mock import patch
from crypto_skills.core import Workspace,SkillError,iso,utc,read_envelope
from crypto_skills import trade,watcher
from crypto_skills.cli import main
import contextlib,io
from tests.test_trade import CONFIG,market,NOW

class WatcherTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.w=Workspace(self.temp.name)
  self.cfg=dict(CONFIG,venue='binance');self.w.write('config',self.cfg,now=NOW)
  m=market();m['venue']='binance';self.w.write('market',m,now=NOW)
  for command in ('entry','plan','size','risk','paper'):
   trade.run(Namespace(workspace=self.temp.name,command=command,now=NOW,action='submit',side='long',price=None))
  self.position=self.w.read('ledger')['data']['positions'][0];self.pid=self.position['id']
 def quote(self,price='102',**changes):
  q={'symbol':'BTCUSDT','venue':'binance','bid':price,'ask':str(Decimal(price)+Decimal('.01')),
     'request_started_at':NOW,'received_at':NOW,
     'source':{'mode':'public_rest','base_url':'https://data-api.binance.vision','endpoint':'/api/v3/ticker/bookTicker'}}
  q.update(changes);return q
 def observe(self,q):return watcher.observe(self.w,self.pid,q,now=NOW)
 def test_new_position_has_its_own_exit_cost_model(self):
  self.assertEqual(self.position['exit_model']['price_tick'],'0.01')
  self.assertEqual(self.position['exit_model']['venue'],'binance')
 def test_no_touch_does_not_mutate_ledger(self):
  before=self.w.read('ledger')['digest'];r=self.observe(self.quote())
  self.assertEqual(r['status'],'holding');self.assertEqual(self.w.read('ledger')['digest'],before)
  self.assertEqual(Decimal(r['estimated_net_pnl']),Decimal('-0.826995'))
 def test_stop_gap_fills_observed_bid_and_reconciles_cash_fees_daily_pnl(self):
  before=self.w.read('ledger')['data'];r=self.observe(self.quote('90'));after=self.w.read('ledger')['data']
  self.assertEqual(r['status'],'closed');order=after['orders'][-1]
  self.assertEqual(order['exit_reason'],'stop_loss');self.assertEqual(Decimal(order['price']),Decimal('89.95'))
  self.assertEqual(after['positions'],[])
  self.assertEqual(Decimal(after['cash']),Decimal(before['cash'])+Decimal(order['price'])*Decimal(order['quantity'])-Decimal(order['fee']))
  self.assertEqual(Decimal(after['cash']),Decimal(after['initial_cash'])+Decimal(after['realized_pnl']))
  self.assertEqual(after['daily_realized']['2026-11-17'],after['realized_pnl'])
 def test_target_uses_current_observed_fill_not_historical_target(self):
  self.observe(self.quote('105'));order=self.w.read('ledger')['data']['orders'][-1]
  self.assertEqual(order['exit_reason'],'take_profit');self.assertEqual(Decimal(order['price']),Decimal('104.94'))
 def test_duplicate_observation_cannot_sell_twice(self):
  self.observe(self.quote('90'));before=self.w.read('ledger')['digest']
  self.assertEqual(self.observe(self.quote('90'))['status'],'already_closed')
  self.assertEqual(self.w.read('ledger')['digest'],before)
 def test_manual_close_before_quote_commit_cannot_sell_twice(self):
  trade.run(Namespace(workspace=self.temp.name,command='paper',now=NOW,action='close',price='102'))
  self.assertEqual(self.observe(self.quote('90'))['status'],'already_closed')
  self.assertEqual(len(self.w.read('ledger')['data']['orders']),2)
 def test_invalid_quotes_never_change_inventory(self):
  for change in ({'symbol':'ETHUSDT'},{'bid':'-1'},{'ask':'0'},{'request_started_at':None},
    {'request_started_at':'2026-11-17T11:59:44Z','received_at':'2026-11-17T11:59:44Z'},
    {'request_started_at':'2026-11-17T12:00:01Z','received_at':'2026-11-17T12:00:01Z'},
    {'source':{'mode':'fixture'}},{'venue':'other'}):
   with self.subTest(change=change):
    before=self.w.read('ledger')['digest']
    with self.assertRaises(SkillError):self.observe(self.quote('90',**change))
    self.assertEqual(self.w.read('ledger')['digest'],before)
 def test_config_symbol_and_tick_change_does_not_reprice_other_position(self):
  self.w.write('config',dict(self.cfg,symbol='SOLUSDT',price_tick='1',fee_rate='.01'),now=NOW)
  self.observe(self.quote('90'));o=self.w.read('ledger')['data']['orders'][-1]
  self.assertEqual(o['symbol'],'BTCUSDT');self.assertEqual(Decimal(o['price']),Decimal('89.95'))
  self.assertEqual(Decimal(o['fee']),Decimal(o['price'])*Decimal(o['quantity'])*Decimal('.001'))
 def test_legacy_archive_is_verified_and_missing_archive_blocks_exit(self):
  ledger=self.w.read('ledger');ledger['data']['positions'][0].pop('exit_model',None)
  self.w.write('ledger',ledger['data'],{'previous_ledger':ledger['digest']},now=NOW)
  # Rebuild projections as if an old-version position is the current authoritative commit.
  trade._account(self.w,self.cfg,utc(NOW))
  with self.assertRaises(SkillError):self.observe(self.quote('90'))
  folder=self.w.root/'assets/BTCUSDT';folder.mkdir(parents=True)
  (folder/'config.json').write_text(json.dumps(self.w.read('config')),encoding='utf-8')
  self.assertEqual(self.observe(self.quote('90'))['status'],'closed')
 def test_run_is_bounded_and_records_source_errors(self):
  args=Namespace(workspace=self.temp.name,now=None,input=None,fetch=False,price=None,duration_seconds=0,poll_seconds=15)
  with patch.object(watcher,'collect_quote',side_effect=SkillError('offline')):
   r=watcher.run(args)
  self.assertEqual(r['data']['status'],'degraded');self.assertEqual(r['data']['cycles'],1)
  self.assertEqual(len(self.w.read('ledger')['data']['positions']),1)
  self.assertFalse(r['data']['running'])
 def test_watch_rejects_history_override_and_invalid_bounds(self):
  for updates in ({'now':NOW},{'price':'100'},{'duration_seconds':-1},{'poll_seconds':1},{'input':'fixture.json'},{'symbol':'ETHUSDT'}):
   a=dict(workspace=self.temp.name,now=None,input=None,fetch=False,price=None,duration_seconds=0,poll_seconds=15);a.update(updates)
   with self.subTest(updates=updates),self.assertRaises(SkillError):watcher.run(Namespace(**a))
 def test_external_envelope_reader_checks_integrity(self):
  p=self.w.state/'config.json';self.assertEqual(read_envelope(p,'config')['data']['symbol'],'BTCUSDT')
  obj=json.loads(p.read_text());obj['data']['symbol']='ETHUSDT';p.write_text(json.dumps(obj))
  with self.assertRaises(SkillError):read_envelope(p,'config')
 def test_cli_watch_runs_one_pass_and_reports_errors_nonzero(self):
  now=iso();q=self.quote(request_started_at=now,received_at=now)
  with patch.object(watcher,'collect_quote',return_value=q),contextlib.redirect_stdout(io.StringIO()) as output:
   self.assertEqual(main(['paper','watch','--workspace',self.temp.name]),0)
  self.assertFalse(json.loads(output.getvalue())['data']['running'])
  with patch.object(watcher,'collect_quote',side_effect=SkillError('offline')),contextlib.redirect_stdout(io.StringIO()):
   self.assertEqual(main(['paper','watch','--workspace',self.temp.name]),1)
 def test_watch_lease_blocks_second_watcher_but_allows_trade_lock(self):
  a=Namespace(workspace=self.temp.name,now=None,input=None,fetch=False,price=None,duration_seconds=0,poll_seconds=15)
  with self.w.lock('watcher'):
   with self.w.lock():pass
   with self.assertRaises(SkillError):watcher.run(a)
 def test_deadline_stops_before_starting_another_poll(self):
  a=Namespace(workspace=self.temp.name,now=None,input=None,fetch=False,price=None,duration_seconds=10,poll_seconds=5)
  now=iso();q=self.quote(request_started_at=now,received_at=now)
  with patch.object(watcher.time,'monotonic',side_effect=[0,2,10]),patch.object(watcher.time,'sleep'),patch.object(watcher,'collect_quote',return_value=q) as get:
   r=watcher.run(a)
  self.assertEqual(get.call_count,1);self.assertEqual(r['data']['cycles'],1)
 def test_interruption_marks_stopped_and_releases_lease(self):
  a=Namespace(workspace=self.temp.name,now=None,input=None,fetch=False,price=None,duration_seconds=0,poll_seconds=15)
  with patch.object(watcher,'_watch_loop',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):watcher.run(a)
  self.assertFalse(self.w.read('watcher')['data']['running'])
  with self.w.lock('watcher'):pass
 def test_projection_failure_recovers_committed_exit_without_duplicate(self):
  a=Namespace(workspace=self.temp.name,now=None,input=None,fetch=False,price=None,duration_seconds=0,poll_seconds=15)
  now=iso();q=self.quote('90',request_started_at=now,received_at=now);failed=[]
  # Patch the class so the watcher-created Workspace encounters the same interrupted projection.
  original=Workspace.write
  def class_flaky(ws,kind,*args,**kwargs):
   if kind=='portfolio' and not failed:failed.append(True);raise OSError('Simulated projection write failure')
   return original(ws,kind,*args,**kwargs)
  with patch.object(Workspace,'write',autospec=True,side_effect=class_flaky),patch.object(watcher,'collect_quote',return_value=q):r=watcher.run(a)
  self.assertEqual(len(r['data']['closed_order_ids']),1)
  self.assertEqual(len(self.w.read('ledger')['data']['orders']),2)
  self.assertEqual(self.w.read('portfolio')['inputs']['ledger'],self.w.read('ledger')['digest'])
 def test_one_symbol_error_does_not_stop_another_symbol_exit(self):
  cfg=dict(self.cfg,symbol='ETHUSDT');self.w.write('config',cfg,now=NOW)
  m=market();m['venue']='binance';m['symbol']='ETHUSDT';m['source']['volume_unit']='ETH'
  self.w.write('market',m,now=NOW)
  for command in ('entry','plan','size','risk','paper'):
   trade.run(Namespace(workspace=self.temp.name,command=command,now=NOW,action='submit',side='long',price=None))
  def quotes(symbol):
   if symbol=='BTCUSDT':raise SkillError('BTC source offline')
   now=iso();return self.quote('90',symbol=symbol,request_started_at=now,received_at=now)
  a=Namespace(workspace=self.temp.name,now=None,input=None,fetch=False,price=None,duration_seconds=0,poll_seconds=15)
  with patch.object(watcher,'collect_quote',side_effect=quotes):r=watcher.run(a)
  self.assertEqual(r['data']['status'],'degraded')
  self.assertEqual([p['symbol'] for p in self.w.read('ledger')['data']['positions']],['BTCUSDT'])
  self.assertEqual(self.w.read('ledger')['data']['orders'][-1]['symbol'],'ETHUSDT')

if __name__=='__main__':unittest.main()
