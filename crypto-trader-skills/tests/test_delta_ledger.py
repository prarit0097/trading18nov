import unittest
from crypto_skills import delta_ledger as d


class DeltaLedgerTests(unittest.TestCase):
    def test_history_query_includes_an_event_exactly_at_its_start(self):
        from datetime import datetime

        expected = 1795027744069005
        convert = getattr(d, 'inclusive_history_start', None)
        self.assertIsNotNone(convert, 'Delta history requests need an inclusive boundary conversion')
        for timestamp in ('2026-11-18T18:49:04.069006Z', '2026-11-19T00:19:04.069006+05:30'):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(convert(datetime.fromisoformat(timestamp)), expected)

    def test_manager_report_is_persisted_against_verified_evidence(self):
        import json
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'runs/delta-demo-loop/reviews.json'
            d.atomic_json(path, {'manager_handoffs':{'ten':{
                'settlement_verified':True, 'evidence_sha256':'current', 'status':'awaiting_manager'}}})
            report = dict(review_id='ten', evidence_sha256='old', execution_findings='Costs recorded',
                          strategy_findings='Collect subsequent data', recommendation='Retain baseline')
            with self.assertRaises(ValueError):
                d.save_manager_review(root, report)
            self.assertEqual(json.loads(path.read_text())['manager_handoffs']['ten']['status'],
                             'awaiting_manager')
            report['evidence_sha256'] = 'current'
            self.assertEqual(d.save_manager_review(root, report)['status'], 'reviewed')
            self.assertEqual(json.loads(path.read_text())['manager_handoffs']['ten']['decision']['recommendation'],
                             'Retain baseline')

    def test_campaign_review_groups_only_eligible_verified_trades(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 11, 18, tzinfo=timezone.utc)
        rows = [dict(order_id=str(i), symbol='BTCUSD', status='closed',
                     closed_at=(now + timedelta(minutes=i)).isoformat(),
                     filled_contracts=10, strategy_version='v1',
                     classification='strategy', net_pnl='1') for i in range(12)]
        rows[1]['symbol'] = 'ADAUSD'
        rows[2]['filled_contracts'] = 5
        queue = {'batches': [{'batch_id': 'legacy'}]}
        campaign = d.refresh_campaign_reviews(queue, rows, now.isoformat())
        self.assertEqual(campaign['batches'][0]['order_ids'], ['0'] + [str(i) for i in range(3, 12)])
        self.assertEqual(len(campaign['manager_handoffs']), 1)
        d.refresh_campaign_reviews(queue, list(reversed(rows)), now.isoformat())
        self.assertEqual(len(campaign['manager_handoffs']), 1)
        self.assertEqual(queue['batches'], [{'batch_id': 'legacy'}])

        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from crypto_skills.delta_research import SPECIALIST_TRACKS

        review_id, handoff = next(iter(campaign['manager_handoffs'].items()))
        report = dict(
            review_id=review_id,
            evidence_sha256=handoff['evidence_sha256'],
            specialists={track: 'No independent evidence of improvement yet' for track in SPECIALIST_TRACKS},
            manager=dict(findings='Ten verified trades', recommendation='Retain the current version'),
            ceo=dict(decision='retain_current', rationale='Independent evidence pending'),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'runs/delta-demo-loop/reviews.json'
            d.atomic_json(path, queue)
            self.assertEqual(d.save_manager_review(directory, report)['status'], 'reviewed')
            saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved['batches'], [{'batch_id': 'legacy'}])
        self.assertEqual(saved['campaign_reviews']['manager_handoffs'][review_id]['decision']['ceo'],
                         report['ceo'])

    def test_known_batch_orders_reconcile_as_one_position(self):
        trade = dict(order_id='a', product_id=84, contracts=20, contract_value='.001',
                     position='long')
        fills = [
            dict(id=order, order_id=order, product_id=84, side=side, size=size,
                 price=price, commission='.1', created_at=f'2026-11-18T00:00:0{i}Z',
                 meta_data={'new_position':{'size':remaining, 'realized_funding':'0'}})
            for i, (order, side, size, price, remaining) in enumerate([
                ('a','buy',10,'64000',10), ('b','buy',10,'64100',20),
                ('x','sell',20,'64500',0),
            ])
        ]
        wallet = [
            dict(id=i+1, product_id=84, transaction_type=kind, amount=amount,
                 created_at=f'2026-11-18T00:00:0{i}Z')
            for i, (kind, amount) in enumerate([
                ('commission','-.1'), ('commission','-.1'), ('commission','-.1'), ('cashflow','9'),
            ])
        ]
        row = d.reconcile_trade(trade, fills, wallet, [], entry_contracts={'a':10, 'b':10})
        self.assertEqual((row['status'], row['filled_contracts'], row['net_pnl']),
                         ('closed',20,'8.7'))
        self.assertEqual(d.reconcile_trade(trade, fills, wallet, [],
                          entry_contracts={'a':10,'c':10})['status'], 'reconciliation_pending')
        lots = [dict(trade, order_id=key, contracts=10, expected_filled_contracts=10,
                     stop_loss='63000', target='64500') for key in ('a','b')]
        result = d.reconcile_batch_position(lots, fills, wallet, [], [])
        indexed = d.ReconciliationHistory(fills, wallet)
        self.assertEqual(d.reconcile_batch_position(lots, fills, wallet, [], [], indexed=indexed), result)
        self.assertEqual([x['status'] for x in result], ['closed','closed'])
        self.assertEqual([x['net_pnl'] for x in result], ['4.85000000','3.85000000'])
        self.assertTrue(all(x['closed_at'] == row['closed_at'] for x in result))
        position = {'product_id':84, 'size':10, 'unrealized_pnl':'1.25'}
        live = d.reconcile_batch_position(lots[:1], fills[:1], [], [position], [])
        self.assertEqual(live[0]['unrealized_pnl'], '1.25')
        combined = d.reconcile_batch_position(lots, fills[:2], [],
                                              [dict(position, size=20)], [])
        self.assertEqual([x['unrealized_pnl'] for x in combined], [None,None])

    def test_flat_funding_reset_reconciles_only_with_continuous_wallet(self):
        trade = dict(order_id='a', product_id=84, contracts=10, contract_value='.001', position='long')
        fills = [
            dict(id=key, order_id=key, product_id=84, side=side, size=10, price=price,
                 commission=fee, created_at=f'2026-11-18T00:00:0{second}Z',
                 meta_data={'new_position':{'size':remaining, 'realized_funding':'-0.00000000'}})
            for key, side, price, fee, second, remaining in [
                ('a','buy','63976','.33971256',0,10), ('b','sell','63188.5','.33553094',4,0)]
        ]
        wallet = [
            dict(id=i, product_id=84, transaction_type=kind, amount=amount, balance=balance,
                 meta_data={'fill_uuid':key}, created_at=f'2026-11-18T00:00:0{i}Z')
            for i, (kind, amount, balance, key) in enumerate([
                ('commission','-.33971256','170.91922441','a'),
                ('funding','-.0649404','170.85428401',None),
                ('funding','-.0648815','170.78940251',None),
                ('cashflow','-7.875','162.91440251',None),
                ('commission','-.33553094','162.57887157','b'),
            ], 1)
        ]
        self.assertEqual(d.reconcile_trade(trade, fills, wallet[::-1], [])['net_pnl'], '-8.68006540')
        self.assertEqual(d.reconcile_trade(trade, fills, wallet[:1]+wallet[2:], [])['status'],
                         'reconciliation_pending')
        # Delta posts a common USD balance after every wallet event across products.
        unrelated = dict(id=99, product_id=999, transaction_type='commission',
                         amount='-.2', balance='170.71922441',
                         created_at='2026-11-18T00:00:01.500000Z')
        from decimal import Decimal
        interleaved = [wallet[0], unrelated] + [
            dict(t, balance=str(Decimal(t['balance']) - Decimal('.2'))) for t in wallet[1:]
        ]
        self.assertEqual(d.reconcile_trade(trade, fills, interleaved[::-1], [])['net_pnl'],
                         '-8.68006540')
        self.assertEqual(d.reconcile_trade(trade, fills, interleaved[:1]+interleaved[2:], [])['status'],
                         'reconciliation_pending')

        del fills[-1]['meta_data']['new_position']['realized_funding']
        indexed = d.ReconciliationHistory(fills, interleaved[::-1])
        self.assertEqual(d.reconcile_trade(trade, fills, interleaved[::-1], [], indexed=indexed)['net_pnl'],
                         '-8.68006540')
        indexed_missing = d.ReconciliationHistory(fills, interleaved[:1]+interleaved[2:])
        self.assertEqual(d.reconcile_trade(trade, fills, interleaved, [], indexed=indexed_missing)['status'],
                         'reconciliation_pending')
        self.assertEqual(d.reconcile_trade(trade, fills, interleaved[:1]+interleaved[2:], [])['status'],
                         'reconciliation_pending')

    def test_single_lot_reconciles_funding_posted_in_the_closing_wallet_bundle(self):
        from decimal import Decimal

        trade = dict(order_id='entry', product_id=1699, contracts=3, expected_filled_contracts=3,
                     contract_value='.01', position='long', stop_loss='1700', target='1800')
        fills = [dict(id=key, order_id=key, product_id=1699, side=side, size=3, price=price,
                      commission=fee, created_at=stamp, meta_data={'new_position':{'size':remaining}})
                 for key,side,price,fee,stamp,remaining in (
                     ('entry','buy','1778','.02832354','2026-11-18T23:58:32Z',3),
                     ('exit','sell','1772.25','.02823195','2026-11-19T00:08:37.330510Z',0))]
        balance = Decimal(200)
        wallet = []
        for index,(kind,amount,stamp,metadata) in enumerate((
                ('commission','-.02832354','2026-11-18T23:58:32.001Z',{'fill_uuid':'entry'}),
                ('funding','-.00533154','2026-11-19T00:08:37.343477Z',{}),
                ('cashflow','-.1725','2026-11-19T00:08:37.345251Z',{'exit_price':'1772.25','position_size':3}),
                ('commission','-.02823195','2026-11-19T00:08:37.345325Z',{'fill_uuid':'exit'}))):
            balance += Decimal(amount)
            wallet.append(dict(id=str(index),product_id=1699,transaction_type=kind,amount=amount,
                               balance=str(balance),created_at=stamp,meta_data=metadata))
        row = d.reconcile_batch_position([trade],fills,wallet,[],[])[0]
        self.assertEqual((row['status'],row.get('funding'),row['net_pnl']),('closed','-0.00533154','-0.23438703'))
        changed = [*wallet[:2],dict(wallet[2],meta_data={'exit_price':'1773','position_size':3}),wallet[3]]
        self.assertEqual(d.reconcile_batch_position([trade],fills,changed,[],[])[0]['status'],
                         'reconciliation_pending')

    def test_zero_gross_close_can_reconcile_with_only_fill_linked_commissions(self):
        trade = dict(order_id='entry', product_id=45, contracts=3, expected_filled_contracts=3,
                     contract_value='1', position='long', stop_loss='.94', target='1.02')
        fills = [dict(id=key, order_id=key, product_id=45, side=side, size=3, price='.9615',
                      commission='.00153168', created_at=stamp, meta_data={'new_position':{'size':remaining}})
                 for key,side,stamp,remaining in (
                     ('entry','buy','2026-11-19T01:52:50.903432Z',3),
                     ('exit','sell','2026-11-19T02:02:57.100043Z',0))]
        wallet = [
            dict(id='w1', product_id=45, transaction_type='commission', amount='-.00153168',
                 balance='200', created_at='2026-11-19T01:52:50.908255Z', meta_data={'fill_uuid':'entry'}),
            dict(id='w2', product_id=45, transaction_type='commission', amount='-.00153168',
                 balance='199.99846832', created_at='2026-11-19T02:02:57.106682Z', meta_data={'fill_uuid':'exit'}),
        ]
        row = d.reconcile_batch_position([trade], fills, wallet, [], [])[0]
        self.assertEqual((row['status'], row['net_pnl'], row['funding']), ('closed', '-0.00306336', '0'))
        for invalid_fills, invalid_wallet in (
            ([fills[0], dict(fills[1], price='.962')], wallet),
            (fills, [wallet[0], dict(wallet[1], balance='199.99')]),
            (fills, [wallet[0], dict(wallet[1], meta_data={'fill_uuid':'other-exit'})]),
        ):
            self.assertEqual(d.reconcile_batch_position([trade], invalid_fills, invalid_wallet, [], [])[0]['status'],
                             'reconciliation_pending')

    def test_partial_exits_and_later_entry_are_attributed_to_separate_lifecycles(self):
        def fill(i, order, side, size, price, remaining, funding=None):
            position = {'size': remaining}
            if funding is not None:
                position['realized_funding'] = funding
            return dict(id=str(i), order_id=order, product_id=84, side=side, size=size,
                        price=price, commission='.1', created_at=f'2026-11-18T00:00:0{i}Z',
                        meta_data={'new_position': position})

        first = {'order_id':'a', 'product_id':84, 'contracts':10, 'contract_value':'.001',
                 'position':'long'}
        second = dict(first, order_id='b')
        fills = [fill(1,'a','buy',10,'64000',10), fill(2,'x','sell',4,'64500',6),
                 fill(3,'y','sell',6,'65000',0,'-.05'), fill(4,'b','buy',10,'65000',10)]
        wallet = [
            dict(id=i, product_id=84, created_at=f'2026-11-18T00:00:0{minute}Z',
                 transaction_type=kind, amount=amount)
            for i, (minute, kind, amount) in enumerate([
                (1,'commission','-.1'), (2,'commission','-.1'), (3,'commission','-.1'),
                (2,'cashflow','2'), (3,'cashflow','6'), (3,'funding','-.05'),
                (4,'commission','-.1')])
        ]
        positions = [{'product_id':84,'size':10,'entry_price':'65000','unrealized_pnl':'1'}]
        a = d.reconcile_trade(first, fills + [fills[1]], wallet, positions)
        b = d.reconcile_trade(second, fills, wallet, positions)
        self.assertEqual((a['status'], a['exit'], a['net_pnl']), ('closed','64800','7.65'))
        self.assertEqual((b['status'], b['unrealized_pnl']), ('open','1'))
        self.assertEqual(d.reconcile_trade(first, fills, wallet[:-2], positions)['status'],
                         'reconciliation_pending')
        conflict = [fills[0], dict(fills[1], side='buy'), *fills[2:]]
        self.assertEqual(d.reconcile_trade(first, conflict, wallet, positions)['status'],
                         'reconciliation_pending')

    def test_duplicate_order_id_does_not_double_count(self):
        row={'order_id':'123','status':'closed','net_pnl':'1','classification':'strategy'}
        with self.assertRaises(ValueError): d.review([row,row])

    def test_nonfinite_pnl_rejected(self):
        with self.assertRaises(ValueError):
            d.review([{'status':'closed','net_pnl':'Infinity','classification':'strategy'}])

    def test_queue_emits_once_per_closed_batch(self):
        rows=[{'order_id':str(i),'closed_at':f'2026-11-18T00:{i:02}:00Z','status':'closed','net_pnl':'1','classification':'strategy','strategy_version':'v1'} for i in range(20)]
        batches=d.batch_reviews(rows,[])
        self.assertEqual(len(batches),2)
        self.assertEqual(len(d.batch_reviews(rows,[batches[0]['batch_id']])),1)
        self.assertEqual(batches[0]['statistics']['closed'],10)
        self.assertFalse(batches[0]['auto_promote'])

    def test_batches_exclude_open_and_pending(self):
        self.assertEqual(d.batch_reviews([{'status':'open','net_pnl':None}],[]),[])

    def test_review_revisions_and_late_settlement_keep_original_membership(self):
        rows=[dict(order_id=str(i), closed_at=f'2026-11-18T00:{i:02}:00Z',
                   status='closed', net_pnl='1', classification='strategy',
                   strategy_version='v1', filled_contracts=10) for i in range(1,20)]
        queue = {'batches':[]}
        d.refresh_batch_reviews(queue, rows)
        first = queue['batches'][0]
        rows[0]['net_pnl'] = '2'
        late = dict(rows[0], order_id='late', closed_at='2026-11-18T00:00:00Z')
        d.refresh_batch_reviews(queue, [late] + rows)
        self.assertEqual(len(queue['batches']), 2)
        self.assertEqual(queue['batches'][0]['batch_id'], first['batch_id'])
        self.assertEqual(queue['batches'][0]['order_ids'], first['order_ids'])
        self.assertEqual(queue['batches'][0]['statistics']['net_pnl'], '11')
        self.assertIn('late', queue['batches'][1]['order_ids'])

    def test_review_distinguishes_break_even(self):
        rows=[{'status':'closed','net_pnl':str(v),'classification':'strategy'} for v in (-2,0,3)]
        r=d.review(rows)
        self.assertEqual((r['wins'],r['losses'],r['breakevens']),(1,1,1))

    def test_open_profit_is_not_completed(self):
        self.assertEqual(d.review([{'status':'open','net_pnl':'5','classification':'strategy'}])['closed'],0)

    def test_manual_excluded_from_strategy_probability(self):
        r=d.review([{'status':'closed','net_pnl':'5','classification':'manual_demo_execution_test'}])
        self.assertEqual(r['closed'],1)
        self.assertEqual(r['strategy_sample'],0)
        self.assertIsNone(r['strategy_win_rate'])

    def test_ten_trade_review_and_uncertainty(self):
        rows=[{'status':'closed','net_pnl':str(2 if i<6 else -1),'classification':'strategy'} for i in range(10)]
        r=d.review(rows)
        self.assertEqual(r['review_batches_due'],1)
        self.assertAlmostEqual(r['strategy_win_rate'],.6)
        self.assertLess(r['wilson_95'][0],.6)
        self.assertGreater(r['wilson_95'][1],.6)
        self.assertEqual(r['net_pnl'],'8')
        self.assertFalse(r['auto_promote'])

    def test_funding_and_gst_use_wallet_amounts(self):
        tx=[{'transaction_type':'commission','amount':'-.4'}, {'transaction_type':'funding','amount':'-.1'}, {'transaction_type':'settlement','amount':'2'}]
        self.assertEqual(d.settled_net(tx,'2','.4',funding_complete=True),'1.5')

    def test_missing_settlement_not_fabricated(self):
        self.assertIsNone(d.settled_net([{'transaction_type':'commission','amount':'-.4'}],'2','.4',funding_complete=True))

    def test_missing_fee_not_fabricated(self):
        self.assertIsNone(d.settled_net([{'transaction_type':'settlement','amount':'2'}],'2','.4',funding_complete=True))

    def test_positive_funding_is_income(self):
        self.assertEqual(d.settled_net([{'transaction_type':'commission','amount':'-.4'}, {'transaction_type':'funding','amount':'.2'}, {'transaction_type':'settlement','amount':'-1'}],'-1','.4',funding_complete=True),'-1.2')

    def test_no_funding_watermark_means_provisional_only(self):
        tx=[{'transaction_type':'commission','amount':'-.4'}, {'transaction_type':'settlement','amount':'2'}]
        self.assertIsNone(d.settled_net(tx,'2','.4'))

    def test_unknown_wallet_transaction_blocks_finalization(self):
        self.assertIsNone(d.settled_net([{'transaction_type':'bonus','amount':'5'}],'0','0',funding_complete=True))
