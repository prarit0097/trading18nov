import hashlib, importlib.util, json, pathlib, traceback
from urllib.parse import urlparse, parse_qs
root=pathlib.Path(__file__).resolve().parent
receipt=root/'python-engine-fixture.json'
try:
 so=root/'depends'/'backtest_py_windows_64bit.so'; buf=so.read_bytes(); official=json.loads((root/'depends'/'md5.json').read_bytes()); assert hashlib.md5(buf).hexdigest()==official[so.name]
 spec=importlib.util.spec_from_file_location('fmz', root/'official_fmz_python.py'); fmz=importlib.util.module_from_spec(spec); spec.loader.exec_module(fmz)
 calls=[]
 def offline(url,body=None):
  split=urlparse(url); assert split.hostname=='q.fmz.com' and split.path=='/data/history' and body is None, url
  q=parse_qs(split.query); symbol=q['symbol'][0]; assert symbol in ('BTC_USDT.swap','BTC_USDT.funding'),url
  assert q['from']==['1789921800'] and q['to']==['1790109000'],url
  calls.append(symbol)
  doc=json.loads((root/(symbol.split('.')[-1]+'.json')).read_bytes()); doc['data']=[row for row in doc['data'] if 1789921800000 <= row[0] <= 1790109000000]; return json.dumps(doc).encode()
 fmz.httpGet=offline
 runtime={}
 ctx=fmz.VCtx('''backtest\nstart: 2026-09-23 00:00:00\nend: 2026-09-23 02:00:00\nperiod: 15m\nbasePeriod: 5m\nexchanges: [{"eid":"Futures_Binance","currency":"BTC_USDT","balance":10000,"stocks":0,"fee":[0.059,0.059]}]\n''',gApis=runtime)
 exchange=runtime['exchange']; sleep=runtime['Sleep']; ticker=exchange.GetTicker()
 assert ticker['Symbol']=='BTC_USDT.swap',ticker
 exchange.SetContractType('swap');exchange.SetDirection('buy'); assert exchange.Buy(-1,.01)
 sleep(600000);exchange.SetDirection('closebuy');assert exchange.Sell(-1,.01)
 sleep(1000); orders=exchange.GetHistoryOrders(); account=exchange.GetAccount()
 assert len(orders)==2 and orders[0]['Offset']==0 and orders[1]['Offset']==1,orders
 gross=(orders[1]['AvgPrice']-orders[0]['AvgPrice'])*.01
 fee=(orders[0]['AvgPrice']+orders[1]['AvgPrice'])*.01*.00059
 assert abs(account['Balance']-(10000+gross-fee))<1e-7,account
 output={'backend_sha256':hashlib.sha256(buf).hexdigest(),'requests':calls,'orders':orders,'ending_cash':account['Balance'],'gross':gross,'fees':fee,'net':gross-fee}
 ctx.Join();receipt.write_text(json.dumps(output,ensure_ascii=False),encoding='utf8')
except BaseException as e:
 receipt.write_text(json.dumps({'error':str(e),'trace':traceback.format_exc()[:3500]},ensure_ascii=False),encoding='utf8'); raise
