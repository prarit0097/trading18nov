import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from crypto_skills import market
from crypto_skills.core import Workspace, SkillError


NOW = '2026-11-17T12:03:00+00:00'
CONFIG = dict(mode='paper',symbol='BTCUSDT', venue='fixture', product_type='spot', quote_currency='USDT',
              max_market_age_seconds=120)


def sample():
    return dict(symbol='BTCUSDT', venue='fixture', product_type='spot', interval_seconds=60,
                as_of=NOW, bid='101', ask='102',
                metadata=dict(qty_step='0.001', price_tick='0.01', min_notional='5'),
                source=dict(mode='fixture', price_unit='USDT', volume_unit='BTC'),
                bars=[dict(time=f'2026-11-17T12:0{i}:00+00:00', open='100', high='103',
                           low='99', close='101', volume='10', closed=True) for i in range(3)])


class MarketTests(unittest.TestCase):
    def test_valid_market_has_normalized_prices_and_health(self):
        out = market.validate_market(sample(), CONFIG, NOW)
        self.assertEqual(out['bars'][0]['close'], '101')
        self.assertEqual(out['health'], dict(valid=True, gaps=[], closed_bars=3))

    def test_rejects_unclosed_duplicate_gapped_bad_ohlc_and_unknown_units(self):
        cases = []
        x=sample(); x['bars'][-1]['closed']=False; cases.append(x)
        x=sample(); x['bars'][-1]['time']=x['bars'][0]['time']; cases.append(x)
        x=sample(); x['bars'].pop(1); cases.append(x)
        x=sample(); x['bars'][0]['high']='99'; cases.append(x)
        x=sample(); x['bars'][0]['volume']='-1'; cases.append(x)
        x=sample(); del x['source']['volume_unit']; cases.append(x)
        x=sample(); x['as_of']='2026-11-17T11:00:00+00:00'; cases.append(x)
        x=sample(); x['ask']='100'; cases.append(x)
        x=sample(); x['bars'][0]['close']=True; cases.append(x)
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(SkillError):
                market.validate_market(raw, CONFIG, NOW)

    def test_failed_refresh_persists_invalid_market(self):
        with tempfile.TemporaryDirectory() as t:
            w=Workspace(t); w.write('config', CONFIG); w.write('market', sample())
            p=Path(t)/'bad.json'; p.write_text('{}')
            args=SimpleNamespace(workspace=t,input=str(p),fetch=False,now=NOW)
            with self.assertRaises(SkillError): market.run(args)
            self.assertFalse(w.read('market')['data']['health']['valid'])

    def test_public_rest_removes_only_current_open_bar_and_uses_exchange_filters(self):
        cfg=dict(CONFIG,venue='binance')
        payloads=[{'symbols':[{'symbol':'BTCUSDT','status':'TRADING','baseAsset':'BTC',
                              'quoteAsset':'USDT','filters':[{'filterType':'LOT_SIZE','stepSize':'0.001'},
                              {'filterType':'PRICE_FILTER','tickSize':'0.01'},
                              {'filterType':'NOTIONAL','minNotional':'5'}]}]},
                  [[1794916800000+i*60000,'100','103','99','101','10',1794916859999+i*60000]
                   for i in range(4)], {'symbol':'BTCUSDT','bidPrice':'101','askPrice':'102'}]
        with patch.object(market,'_get_json',side_effect=payloads):
            out=market.fetch_market(cfg,'BTCUSDT','1m',4,NOW)
        self.assertEqual(len(out['bars']),3)
        self.assertEqual(out['metadata']['qty_step'],'0.001')
        self.assertEqual(out['source']['mode'],'public_rest')


if __name__ == '__main__': unittest.main()
