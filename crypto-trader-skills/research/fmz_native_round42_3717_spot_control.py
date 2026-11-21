"""Observe Binance Spot order units, fees and call clocks in the offline FMZ engine."""
import argparse
import calendar
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).absolute().parent
START = 1627776000000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    arg=argparse.ArgumentParser(description=__doc__)
    arg.add_argument('--receipt', default='round42-3717-abi.json')
    args=arg.parse_args()
    raw = (ROOT / 'round42-3717-feed.json').read_bytes()
    source = json.loads(raw)
    assert source['detail']['eid'] == 'Binance' and source['detail']['baseCurrency'] == 'BTC'
    loader = ROOT/'official_fmz_python.py'
    binary = digest((ROOT/'depends/backtest_py_windows_64bit.so').read_bytes())
    assert binary == '504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0'
    spec = importlib.util.spec_from_file_location('fmz',loader)
    fmz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fmz)

    def offline(url, body=None):
        p = urlparse(url)
        query = parse_qs(p.query)
        assert p.hostname == 'q.fmz.com' and p.path == '/data/history' and body is None
        assert query['eid'] == ['Binance'] and query['symbol'] == ['BTC_USDT'] and query['period'] == ['60000']
        t0,t1 = [int(query[k][0])*1000 for k in ('from','to')]
        payload = {k:source[k] for k in ('detail','schema')}
        data = [row for row in source['data'] if t0 <= row[0] <= t1]
        assert data
        payload['data'] = data
        return json.dumps(payload).encode()

    fmz.httpGet = offline
    config = '''backtest
start: 2021-08-01 00:00:00
end: 2021-08-01 00:09:00
period: 1m
basePeriod: 1m
exchanges: [{"eid":"Binance","currency":"BTC_USDT","balance":1000000,"stocks":0,"fee":[0.06,0.075]}]
'''
    api = {}
    actual_time = time.time
    local_mktime = time.mktime
    try:
        time.mktime = calendar.timegm
        ctx = fmz.VCtx(config, gApis=api)
    finally:
        time.mktime = local_mktime
    clock = lambda: api['UnixNano']() // 1_000_000
    e = api['exchange']
    proof = []

    def call(name, *values):
        before = clock()
        ret = getattr(e, name)(*values)
        proof.append({'call':name, 'args':values, 'before':before, 'after':clock(), 'result':ret})
        return ret

    try:
        assert START <= clock() < START+60_000, clock()
        call('SetCurrency','BTC_USDT')
        call('SetPrecision',2,5)
        call('GetAccount')
        call('GetTicker')
        depth = call('GetDepth')
        qty = api['_N'](depth['Asks'][0]['Price']*.1,2)
        oid = call('Buy',-1,qty)
        assert oid
        call('GetOrder',oid)
        call('GetHistoryOrders')
        call('GetAssets')
        account = call('GetAccount')
        quote = call('GetTicker')
        far_sell = call('Sell',quote['Last']+100,.02)
        far_buy = call('Buy',quote['Last']-100,.02)
        assert far_sell and far_buy
        call('GetOrder',far_sell)
        call('GetOrder',far_buy)
        call('GetAccount')
        api['Sleep'](1000)
        call('GetAccount')
    finally:
        time.time = actual_time
        ctx.Join()
    (ROOT/args.receipt).write_text(json.dumps({'calls':proof,'data':digest(raw),'backend':binary,
                                              'loader':digest(loader.read_bytes())}),encoding='utf-8')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        (ROOT/'round42-3717-abi-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
