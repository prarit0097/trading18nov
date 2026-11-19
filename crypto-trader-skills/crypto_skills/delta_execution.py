"""Prepare and recover authenticated demo entries by client order ID."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from math import isfinite
import time

from .core import Workspace
from .delta_plan import CRYPTO_DEMO_SYMBOLS, LEGACY_CONTRACTS, MIN_BATCH_COINS, TRADE1_CONTRACTS, next_batch_size

BATCH_POLICY = 'delta-demo-five-coin-v6'


async def execute_entry(call, journal, proposal, signals, campaign, inventory_clear, stopped):
    """Attempt one supervised testnet entry from a checked account snapshot."""
    from .delta_signal import preview

    if proposal['status'] != 'planned':
        return {'status':proposal['status']}
    if stopped() or time.time() >= proposal['expires_at']:
        return {'status':'stopped_or_expired'}
    if journal.attempted(proposal['signal_id']):
        return {'status':'signal_already_attempted'}
    await OrderJournal._check_environment(call)
    if not await inventory_clear():
        return {'status':'account_changed'}

    plan = proposal['plan']
    args = {'product_id':plan['product_id']}
    actual = (await call('get_product_leverage', args))['result']
    if Decimal(actual['leverage']) != plan['leverage']:
        if stopped():
            return {'status':'stopped_or_expired'}
        await call('set_product_leverage', dict(args, leverage=str(plan['leverage'])))
        actual = (await call('get_product_leverage', args))['result']
    if Decimal(actual['leverage']) != plan['leverage']:
        return {'status':'leverage_unconfirmed'}

    fresh = await preview(call, signals, campaign)
    if (fresh['status'] != 'planned' or fresh['signal_id'] != proposal['signal_id']
            or fresh['plan']['product_id'] != plan['product_id']
            or fresh['plan']['leverage'] != plan['leverage']):
        return {'status':'plan_changed'}
    if not await inventory_clear():
        return {'status':'account_changed'}

    intent = await journal.submit(call, fresh['plan'], fresh['signal']['version'],
                                  fresh['signal_id'],
                                  signal=fresh['signal'],
                                  can_send=lambda: not stopped() and time.time() < fresh['expires_at'])
    return {'status':intent['state'], 'client_order_id':intent['client_order_id']}


def verified_protection(trade, orders):
    """Verify both exchange exits cover exactly the remaining position."""
    quantity = trade['remaining_contracts']
    expected = {'stop_loss_order': Decimal(trade['stop_loss']),
                'take_profit_order': Decimal(trade['target'])}
    brackets = [order for order in orders
                if order['product_id'] == trade['product_id'] and order.get('bracket_order') is True]
    if len(brackets) != 2 or {order.get('stop_order_type') for order in brackets} != expected.keys():
        return False
    close_side = 'sell' if trade['position'] == 'long' else 'buy'
    return all(
        order['side'] == close_side and order.get('reduce_only') is True
        and order['state'] == 'pending' and order['stop_trigger_method'] == 'mark_price'
        and order['unfilled_size'] == quantity
        and Decimal(order['stop_price']) == expected[order['stop_order_type']]
        for order in brackets
    )


async def execute_batch(call, pages, journal, proposal, signals, campaign, inventory_clear, stopped,
                        *, contracts=LEGACY_CONTRACTS):
    """Run the bounded, journaled testnet cohort after fresh exchange checks."""
    from .delta_signal import preview_batch

    if proposal['status'] != 'planned':
        return {'status':proposal['status']}
    needed = next_batch_size(campaign['completed'])
    if needed == 0:
        return {'status':'target_reached'}

    def valid_cohort(entries):
        symbols = {entry['symbol'] for entry in entries}
        products = {entry['product_id'] for entry in entries}
        return len(entries) == len(symbols) == len(products) == needed and symbols.issubset(CRYPTO_DEMO_SYMBOLS)

    if not valid_cohort(proposal['entries']):
        return {'status':'insufficient_distinct_coins'}
    if stopped():
        return {'status':'stopped'}
    if (type(contracts) is not int or contracts not in (LEGACY_CONTRACTS, TRADE1_CONTRACTS)
            or any(row.get('contracts') != contracts for row in proposal['entries'])):
        return {'status':'invalid_contract_size'}
    await OrderJournal._check_environment(call)
    if not await inventory_clear():
        return {'status':'account_changed'}
    planned_leverage = {row['product_id']:row['leverage'] for row in proposal['entries']}
    for product, leverage in planned_leverage.items():
        args = {'product_id':product}
        actual = (await call('get_product_leverage', args))['result']
        if Decimal(actual['leverage']) != leverage:
            if stopped():
                return {'status':'stopped'}
            await call('set_product_leverage', dict(args, leverage=str(leverage)))
            actual = (await call('get_product_leverage', args))['result']
        if Decimal(actual['leverage']) != leverage:
            return {'status':'leverage_unconfirmed'}
    if not await inventory_clear():
        return {'status':'account_changed'}
    fresh = await preview_batch(call, signals, campaign, contracts=contracts)
    if (fresh['status'] != 'planned'
            or not valid_cohort(fresh['entries'])
            or any(row.get('contracts') != contracts for row in fresh['entries'])
            or any(planned_leverage.get(e['product_id']) != e['leverage'] for e in fresh['entries'])):
        return {'status':'plan_changed'}
    terms = {entry['product_id']:entry for entry in fresh['entries']}
    ist = timezone(timedelta(hours=5, minutes=30))
    quote_expiry = fresh['expires_at']
    reserves = [Decimal(row['margin_reserve']) for row in fresh['entries']]
    stop_detail = None
    quote_check_failure = None

    def reject(reason):
        nonlocal stop_detail
        stop_detail = reason
        return False

    def protected(product, quantity, orders):
        return verified_protection(dict(product_id=product, position='long',
            remaining_contracts=quantity, stop_loss=terms[product]['stop'],
            target=terms[product]['target']), orders)

    async def check_before(intent, expected):
        nonlocal quote_expiry, quote_check_failure
        product = intent['plan']['product_id']
        positions = (await call('get_margined_positions', {}))['result']
        if any(Decimal(str(p['size'])) and not expected.get(p['product_id']) for p in positions):
            return reject('Unexpected account position')
        orders = await pages('get_open_orders', {'page_size':50})
        if any(not expected.get(o['product_id']) or o.get('bracket_order') is not True for o in orders):
            return reject('Unexpected open order')
        if any(qty and not protected(pid, qty, orders) for pid, qty in expected.items()):
            return reject('Existing bracket does not cover registered quantity')
        products_to_check = [pid for pid, size in expected.items() if size or pid == product]
        current = await asyncio.gather(*(call('get_positions', {'product_id':pid})
                                         for pid in products_to_check))
        if any(Decimal(str(result['result']['size'])) != expected[pid]
               for pid, result in zip(products_to_check, current)):
            return reject('Exchange size differs from registered fills')
        wallet, quote = await asyncio.gather(
            call('get_wallet_balances', {}), call('get_ticker', {'symbol':intent['plan']['symbol']}))
        cash = next(Decimal(item['available_balance']) for item in wallet['result']
                    if item['asset_symbol'] == 'USD')
        required_margin = sum(reserves[intent['batch_slot']-1:])
        if cash < required_margin:
            return reject('Insufficient available margin for remaining lots')
        tick = quote['result']
        tick_time = float(tick['timestamp']) / 1e6
        checked_at = time.time()
        age = checked_at - tick_time
        ask, bid = (Decimal(tick['quotes'][key]) for key in ('best_ask','best_bid'))
        mark = Decimal(tick['mark_price'])
        limit = Decimal(intent['plan']['limit'])
        stop, target = (Decimal(terms[product][key]) for key in ('stop','target'))
        valid_book = bid.is_finite() and ask.is_finite() and 0 < bid <= ask
        spread = (ask - bid) / bid if valid_book else None
        checks = (
            ('product_mismatch', tick['product_id'] != product),
            ('outside_quote_age_limit', not 0 <= age < 15),
            ('invalid_bid_ask', not valid_book),
            ('ask_above_ioc_limit', valid_book and ask > limit),
            ('spread_above_limit', spread is not None and spread > Decimal('.003')),
            ('mark_outside_bracket', not mark.is_finite() or not stop < mark < target),
        )
        reasons = [reason for reason, failed in checks if failed]
        if reasons:
            symbol = intent['plan']['symbol']
            quote_check_failure = dict(symbol=symbol, reasons=reasons, expected_product_id=product,
                quote_product_id=tick['product_id'], quote_timestamp_us=tick['timestamp'] if isfinite(age) else None,
                quote_age_seconds=age if isfinite(age) else None, bid=str(bid), ask=str(ask), limit=str(limit), mark=str(mark),
                stop=str(stop), target=str(target), spread_fraction=str(spread) if spread is not None else None)
            intent['quote_check_failure'] = quote_check_failure
            return reject(f"Quote or mark moved outside saved bounds for {symbol}")
        intent['preflight_quote'] = dict(exchange_timestamp_us=tick['timestamp'],
            checked_at=datetime.fromtimestamp(checked_at, timezone.utc).isoformat(),
            bid=str(bid), ask=str(ask), mark=str(mark), spread_fraction=str(spread),
            available_margin_usd=str(cash), required_margin_usd=str(required_margin))
        quote_expiry = tick_time + 15
        return True

    async def verify(intent, quantity):
        product = intent['plan']['product_id']
        for attempt in range(3):
            position = (await call('get_positions', {'product_id':product}))['result']
            orders = await pages('get_open_orders', {'product_ids':[product], 'page_size':50})
            if Decimal(str(position['size'])) == quantity and protected(product, quantity, orders):
                return True
            if attempt < 2:
                await asyncio.sleep(.25)
        return reject('Post-fill position or protective bracket could not be confirmed')

    def can_send():
        if stopped():
            return reject('Entry disabled before submission')
        if datetime.now(ist).date().isoformat() != campaign['trading_day_ist']:
            return reject('IST trading day changed')
        return time.time() < quote_expiry or reject('Quote expired before submission')

    if not can_send():
        return {'status':'stopped_or_expired'}
    batch_id = f"demo-{time.time_ns()}"
    intents = await journal.submit_batch(call, fresh, batch_id, verify=verify,
                                         check_before=check_before, can_send=can_send,
                                         stop_reason=lambda: stop_detail,
                                         contracts=contracts)
    fills = [row for row in intents if row['state'] == 'filled']
    result = dict(status='batch_attempted', batch_id=batch_id, filled_lots=len(fills),
                full_lots=sum(row['order']['unfilled_size'] == 0 for row in fills),
                abandoned_lots=sum(row['state']=='batch_abandoned' for row in intents),
                stop_detail=stop_detail,
                unresolved=any(row['state']=='submitted_unknown' for row in intents),
                protection_unconfirmed=any(not row.get('protection_verified') for row in fills))
    if quote_check_failure is not None:
        result['quote_check_failure'] = quote_check_failure
    return result


class OrderJournal:
    def __init__(self, path):
        self.path = path

    def _read(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else []

    def attempted(self, signal_id):
        return any(intent['signal_id'] == signal_id for intent in self._read())

    def _save(self, entries):
        from .delta_ledger import atomic_json
        atomic_json(self.path, entries)

    @staticmethod
    async def _check_environment(call):
        status = await call('get_connection_status', {})
        if status.get('environment') != 'india_testnet':
            raise RuntimeError('Only Delta india_testnet is authorized')

    @staticmethod
    def _accept(intent, order):
        plan = intent['plan']
        if (order['client_order_id'] != intent['client_order_id']
                or order['product_id'] != plan['product_id']
                or order['side'] != plan['side'] or order['size'] != plan['contracts']):
            raise RuntimeError('Exchange order does not match saved intent')
        if order['state'] not in ('closed', 'cancelled'):
            return
        filled = order['size'] - order['unfilled_size']
        if not 0 <= filled <= plan['contracts']:
            raise RuntimeError('Invalid exchange fill quantity')
        if filled:
            price = Decimal(order['average_fill_price'])
            if not price.is_finite() or price <= 0 or price > Decimal(plan['limit']):
                raise RuntimeError('Entry fill violates saved price bound')
            if datetime.fromisoformat(order['created_at']).utcoffset() is None:
                raise RuntimeError('Exchange order timestamp has no offset')
        intent.update(state='filled' if filled else 'unfilled', order=order)

    async def recover(self, call):
        with Workspace(self.path.parent).lock('delta-order-intents'):
            entries = self._read()
            if self._abandon_staged(entries, 'Recovered staged lot before submission'):
                self._save(entries)
            pending = [intent for intent in entries if intent['state'] == 'submitted_unknown']
            if pending:
                await self._check_environment(call)
            for intent in pending:
                try:
                    result = await call('get_order_by_id', {'client_order_id':intent['client_order_id']})
                except RuntimeError:
                    # A failed lookup does not establish that the order was absent.
                    continue
                self._accept(intent, result['result'])
                self._save(entries)
            return any(intent['state'] == 'submitted_unknown' for intent in entries)

    @staticmethod
    def _abandon_staged(entries, reason):
        staged = [entry for entry in entries if entry['state'] == 'batch_staged']
        for entry in staged:
            entry.update(state='batch_abandoned', batch_stop_reason=reason)
        return bool(staged)

    @staticmethod
    def _ioc(intent, *, attach_protection=True):
        plan = intent['plan']
        request = dict(product_id=plan['product_id'], size=plan['contracts'], side='buy', order_type='limit_order',
                       limit_price=plan['limit'], time_in_force='ioc',
                       client_order_id=intent['client_order_id'])
        if attach_protection:
            request.update(bracket_stop_loss_price=plan['stop'],
                           bracket_take_profit_price=plan['target'],
                           bracket_stop_trigger_method='mark_price')
        return request

    async def submit_batch(self, call, batch, batch_id, *, verify,
                           check_before=None, can_send=lambda: True, stop_reason=lambda: None,
                           contracts=LEGACY_CONTRACTS):
        """Commit every lot before submitting, and confirm protection after each fill."""
        with Workspace(self.path.parent).lock('delta-order-intents'):
            history = self._read()
            if any(row['state'] in ('submitted_unknown','batch_staged') for row in history):
                raise RuntimeError('Unresolved orders block a new batch')
            if any(row.get('batch_id') == batch_id for row in history):
                raise RuntimeError('Batch was already attempted')
            plans = batch['entries']
            if type(contracts) is not int or contracts not in (LEGACY_CONTRACTS, TRADE1_CONTRACTS):
                raise ValueError('Unsupported batch contract size')
            if (batch['status'] != 'planned' or not 1 <= len(plans) <= 10
                    or len(plans) != batch['requested_entries']
                    or [e['lot_number'] for e in plans] != list(range(1,len(plans)+1))):
                raise ValueError('Invalid batch plan')
            if contracts == TRADE1_CONTRACTS and (
                    len(plans) > MIN_BATCH_COINS
                    or len({plan['product_id'] for plan in plans}) != len(plans)
                    or len({plan['symbol'] for plan in plans}) != len(plans)):
                raise ValueError('Trade 1 requires distinct coins')
            groups = {}
            total_risk = total_margin = Decimal(0)
            for plan in plans:
                if (plan['environment'] != 'india_testnet' or plan['side'] != 'buy'
                        or type(plan['contracts']) is not int or plan['contracts'] != contracts
                        or plan['symbol'] not in CRYPTO_DEMO_SYMBOLS):
                    raise ValueError('Unsupported batch product or order')
                risk, margin, stop, limit, target = (Decimal(plan[key]) for key in
                    ('planned_loss','margin_reserve','stop','limit','target'))
                if (not all(x.is_finite() for x in (risk, margin, stop, limit, target))
                        or not (0 < risk <= 10 and margin > 0 and 0 < stop < limit < target)):
                    raise ValueError('Invalid batch risk or bracket')
                terms = (plan['symbol'], stop, target, plan['leverage'])
                if groups.setdefault(plan['product_id'], terms) != terms:
                    raise ValueError('Repeated product has inconsistent bracket or leverage terms')
                total_risk += risk
                total_margin += margin
            if not (total_risk <= min(Decimal(30), Decimal(batch['daily_risk_budget']))
                    and total_margin <= Decimal(batch['margin_budget'])):
                raise ValueError('Batch exceeds total planned risk or margin')
            await self._check_environment(call)
            observed_at = datetime.now(timezone.utc).isoformat()
            intents = []
            for plan in plans:
                slot = plan['lot_number']
                signal_id = f'{batch_id}:{slot}'
                client_id = 'cts-' + hashlib.sha256(signal_id.encode()).hexdigest()[:24]
                intents.append(dict(batch_id=batch_id, batch_slot=slot,
                                    position_episode_id=f"{batch_id}:{plan['product_id']}",
                                    signal_id=signal_id, client_order_id=client_id, plan=plan,
                                    strategy_version=BATCH_POLICY, entry_observed_at=observed_at,
                                    signal=dict(plan['signal']), state='batch_staged'))
            history.extend(intents)
            self._save(history)
            filled_by_product = {key:0 for key in groups}
            try:
                for intent in intents:
                    if not can_send():
                        break
                    product = intent['plan']['product_id']
                    before = filled_by_product[product]
                    if check_before is not None and not await check_before(intent, dict(filled_by_product)):
                        break
                    if not can_send():
                        break
                    intent.update(state='submitted_unknown',
                                  submission_started_at=datetime.now(timezone.utc).isoformat())
                    self._save(history)
                    result = await call('place_order', self._ioc(intent, attach_protection=not before))
                    self._accept(intent, result['result'])
                    self._save(history)
                    if intent['state'] == 'submitted_unknown':
                        break
                    if intent['state'] == 'filled':
                        order = intent['order']
                        filled_by_product[product] += order['size'] - order['unfilled_size']
                        intent['protection_verified'] = bool(await verify(intent, filled_by_product[product]))
                        self._save(history)
                        if not intent['protection_verified']:
                            break
            finally:
                reason = stop_reason()
                if not reason and any(intent['state'] == 'submitted_unknown' for intent in intents):
                    reason = 'An earlier submission outcome is unknown'
                if self._abandon_staged(intents, reason or 'Batch ended before this lot was submitted'):
                    self._save(history)
            return intents

    async def submit(self, call, plan, strategy_version, signal_id, *, signal=None,
                     can_send=lambda: True):
        """Send a single IOC entry. An uncertain response is resolved by lookup."""
        with Workspace(self.path.parent).lock('delta-order-intents'):
            entries = self._read()
            if any(intent['state'] == 'submitted_unknown' for intent in entries):
                raise RuntimeError('An unresolved order must be reconciled first')
            if any(intent['signal_id'] == signal_id for intent in entries):
                raise RuntimeError('This signal was already attempted')
            await self._check_environment(call)
            if (plan['environment'] != 'india_testnet' or plan['contracts'] != 10
                    or plan['side'] != 'buy' or plan['symbol'] not in ('BTCUSD','ETHUSD','SOLUSD')):
                raise ValueError('Unsupported demo order plan')
            risk = Decimal(plan['planned_loss'])
            stop, limit, target = (Decimal(plan[key]) for key in ('stop','limit','target'))
            if not (0 < risk <= 10 and 0 < stop < limit < target):
                raise ValueError('Demo order exceeds risk limits or has invalid exit levels')
            client_id = 'cts-' + hashlib.sha256(signal_id.encode()).hexdigest()[:24]
            intent = dict(client_order_id=client_id, signal_id=signal_id, plan=plan,
                          strategy_version=strategy_version, state='submitted_unknown')
            if signal is not None:
                intent['signal'] = dict(signal)
            entries.append(intent)
            self._save(entries)
            if not can_send():
                intent['state'] = 'stopped_or_expired'
                self._save(entries)
                return intent
            result = await call('place_order', self._ioc(intent))
            self._accept(intent, result['result'])
            self._save(entries)
            return intent

    def trades(self):
        for intent in self._read():
            if intent['state'] != 'filled':
                continue
            plan, order = intent['plan'], intent['order']
            row = dict(order_id=str(order['id']), symbol=plan['symbol'], position='long',
                       contracts=plan['contracts'], product_id=plan['product_id'],
                       contract_value=str(Decimal(plan['quantity'])/plan['contracts']),
                       entry=order['average_fill_price'], leverage=plan['leverage'],
                       stop_loss=plan['stop'], target=plan['target'],
                       planned_risk=plan['planned_loss'], opened_at=order['created_at'],
                       classification='strategy', strategy_version=intent['strategy_version'])
            if 'signal' in intent:
                row['signal'] = intent['signal']
            if 'batch_id' in intent:
                row.update({key:intent[key] for key in ('batch_id','batch_slot','position_episode_id',
                                                        'entry_observed_at')})
                row.update(expected_filled_contracts=order['size'] - order['unfilled_size'],
                           entry_policy_version=intent['strategy_version'],
                           signal_status_at_entry=intent['signal']['status'])
                if 'turnover_usd' in plan:
                    row['turnover_usd_at_entry'] = plan['turnover_usd']
            yield row
