from decimal import Decimal
import unittest

from crypto_skills.delta_candidate_entry import book_fill, evaluate_entry
from crypto_skills.delta_plan import CRYPTO_DEMO_SYMBOLS


class CandidateEntryTests(unittest.TestCase):
    def test_ioc_is_bounded_by_price_and_visible_quantity(self):
        asks=[{'price':'100','size':1},{'price':'100.01','size':2},{'price':'100.02','size':7}]
        fill=book_fill(asks,3,'100.01')
        self.assertEqual(fill['filled'],3)
        self.assertEqual(Decimal(fill['avg_price']),Decimal('300.02')/3)
        partial=book_fill(asks,3,'100')
        self.assertEqual(partial['filled'],1)
        self.assertEqual(partial['state'],'partial')

    def test_hidden_depth_is_unresolved(self):
        asks=[{'price':str(Decimal(100)+Decimal('.01')*i),'size':1} for i in range(5)]
        self.assertEqual(book_fill(asks,6,'101')['state'],'depth_unresolved')
        self.assertEqual(book_fill(asks,6,'100.03')['state'],'partial')

    def test_ready_arm_never_substitutes_waiting_coins(self):
        slot=600000
        products={}
        coins={}
        for i,symbol in enumerate(CRYPTO_DEMO_SYMBOLS,start=1):
            products[symbol]=dict(id=i,symbol=symbol,contract_type='perpetual_futures',
                contract_value='1',contract_unit_currency=symbol[:-3],underlying_asset={'symbol':symbol[:-3]},
                quoting_asset={'symbol':'USD'},settling_asset={'symbol':'USD'},tick_size='.0001',
                taker_commission_rate='.0005',trading_status='operational',notional_type='vanilla',is_quanto=False)
            coins[symbol]=dict(status='valid',signal={'closed_at':slot,'status':'ready' if i<=3 else 'waiting'},
                ticker={'symbol':symbol,'product_id':i,'timestamp':slot*1000000,'quotes':{'best_bid':'.5000','best_ask':'.5001'},
                       'mark_price':'.5001','turnover_usd':i},
                book={'symbol':symbol,'sell':[{'price':'.5001','size':10}]})
        snapshot=dict(complete=True,captured_at=slot+4,coins=coins)
        baseline=evaluate_entry(snapshot,products,slot,cash='160',day_loss='1',ready_only=False)
        ready=evaluate_entry(snapshot,products,slot,cash='160',day_loss='1',ready_only=True)
        self.assertEqual(baseline['status'],'modeled_entry')
        self.assertEqual(baseline['full_lots'],4)
        self.assertEqual(ready['status'],'insufficient_distinct_coins')
        self.assertEqual(ready['fills'],[])
        snapshot['complete']=False
        self.assertEqual(evaluate_entry(snapshot,products,slot,cash='160',day_loss='1',ready_only=False)['status'],
                         'incomplete_market_evidence')
