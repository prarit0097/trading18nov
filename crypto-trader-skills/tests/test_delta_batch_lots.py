import unittest
from decimal import Decimal

from crypto_skills.delta_batch_lots import allocate_lots


class BatchLotTests(unittest.TestCase):
    def setUp(self):
        self.entries = [dict(order_id=key, contracts=10, product_id=84, contract_value='1')
                        for key in ('a', 'b')]

    def fill(self, order_id, at, side, size, price, fee, remaining):
        return dict(id=order_id, order_id=order_id, product_id=84, side=side,
                    size=size, price=price, commission=fee, created_at=f'2026-11-18T15:00:0{at}Z',
                    meta_data={'new_position':{'size':remaining}})

    def test_fifo_and_exact_cost_conservation(self):
        fills = [self.fill('a', 1, 'buy', 10, '100', '.10', 10),
                 self.fill('b', 2, 'buy', 10, '110', '.10', 20),
                 self.fill('x', 4, 'sell', 12, '120', '.12', 8),
                 self.fill('y', 5, 'sell', 8, '115', '.08', 0)]
        funding = [dict(id='f1', product_id=84, amount='-.21000001',
                        created_at='2026-11-18T15:00:03Z')]
        partial = allocate_lots(self.entries, fills[:-1], funding)
        self.assertEqual(partial['remaining_contracts'], 8)
        self.assertEqual(partial['lots']['a']['remaining_contracts'], 0)
        self.assertIsNone(partial['lots']['a']['net_pnl'])
        self.assertEqual(partial['lots']['b']['remaining_contracts'], 8)

        result = allocate_lots(self.entries, fills[::-1], funding)
        self.assertEqual(result['remaining_contracts'], 0)
        self.assertEqual(result['lots']['a']['exit'], '120')
        self.assertEqual(result['lots']['b']['exit'], '116')
        self.assertEqual(Decimal(result['lots']['a']['net_pnl']), Decimal('199.695'))
        self.assertEqual(Decimal(result['lots']['b']['net_pnl']), Decimal('59.69499999'))
        self.assertEqual(Decimal(result['net_pnl']), Decimal('259.38999999'))

    def test_external_order_or_oversell_is_rejected(self):
        fills = [self.fill('a', 1, 'buy', 10, '100', '.1', 10),
                 self.fill('foreign', 2, 'buy', 10, '101', '.1', 20)]
        with self.assertRaises(ValueError):
            allocate_lots(self.entries, fills, [])
        fills[-1] = self.fill('x', 2, 'sell', 11, '101', '.1', -1)
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            allocate_lots(self.entries, fills, [])

    def test_tied_buy_and_sell_timestamps_are_ambiguous(self):
        fills = [self.fill('a', 1, 'buy', 6, '100', '.1', 6),
                 self.fill('b', 2, 'buy', 10, '101', '.1', 16),
                 self.fill('x', 2, 'sell', 16, '102', '.16', 0)]
        with self.assertRaisesRegex(ValueError, 'timestamps'):
            allocate_lots(self.entries, fills, [])

    def test_partial_entry_remains_six_contracts_after_group_close(self):
        fills = [self.fill('a', 1, 'buy', 6, '100', '.06', 6),
                 self.fill('b', 2, 'buy', 10, '101', '.10', 16),
                 self.fill('x', 3, 'sell', 16, '102', '.16', 0)]
        rows = allocate_lots(self.entries, fills + [fills[0]])['lots']
        self.assertEqual(rows['a']['filled_contracts'], 6)
        self.assertEqual(rows['a']['exited_contracts'], 6)
        self.assertEqual(rows['b']['filled_contracts'], 10)

    def test_three_contract_lot_reconciles_without_upgrading_partial_fills(self):
        entry = dict(self.entries[0], contracts=3)
        for size in (2, 3):
            fills = [self.fill('a', 1, 'buy', size, '100', '.06', size),
                     self.fill('x', 2, 'sell', size, '101', '.08', 0)]
            lot = allocate_lots([entry], fills)['lots']['a']
            self.assertEqual((lot['filled_contracts'], lot['exited_contracts']), (size, size))
            self.assertEqual(Decimal(lot['net_pnl']), Decimal(size) - Decimal('.14'))
