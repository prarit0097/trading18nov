"""Apply the crypto-entry breakout rule to Delta demo five-minute candles."""
import asyncio
from decimal import Decimal
import time

from .trade import breakout_observation
from .delta_plan import CRYPTO_DEMO_SYMBOLS, LEGACY_CONTRACTS, next_batch_size, plan, plan_batch

SYMBOLS = ('BTCUSD', 'ETHUSD', 'SOLUSD')
INTERVAL = 300
LOOKBACK = 20
VERSION = 'delta-5m-breakout20-v1'


def closed_breakout(candles, now):
    by_time = {}
    for candle in candles:
        opened = candle['time']
        if type(opened) is not int or opened % INTERVAL:
            raise ValueError('Candle timestamp is not aligned to the five-minute interval')
        if opened + INTERVAL > now:
            continue
        if opened in by_time:
            raise ValueError('Candle data has a duplicate timestamp')
        by_time[opened] = candle
    latest = int(now // INTERVAL) * INTERVAL - INTERVAL
    if latest not in by_time:
        raise ValueError('Latest closed candle is stale or missing')
    window = list(range(latest - LOOKBACK * INTERVAL, latest + INTERVAL, INTERVAL))
    if any(opened not in by_time for opened in window):
        raise ValueError('Candle history has a gap or lacks enough data')
    bars = [by_time[opened] for opened in window]
    for bar in bars:
        low, high, op, close, volume = (
            Decimal(str(bar[key])) for key in ('low', 'high', 'open', 'close', 'volume')
        )
        if (not all(value.is_finite() for value in (low, high, op, close, volume))
                or not (0 < low <= min(op, close) <= max(op, close) <= high)
                or volume < 0):
            raise ValueError('Invalid OHLCV candle')
    entry, level, rvol, triggered = breakout_observation(bars[-1], bars[:-1], 'long')
    return dict(status='ready' if triggered else 'waiting', closed_at=latest + INTERVAL,
                entry=str(entry), breakout_level=str(level), rvol=str(rvol), version=VERSION)


async def scan(call, symbols=SYMBOLS):
    observations = {}
    for symbol in symbols:
        end = int(time.time())
        try:
            response = await call('get_candles', dict(symbol=symbol, resolution='5m',
                                  start=end - (LOOKBACK + 3) * INTERVAL, end=end))
            observations[symbol] = closed_breakout(response['result'], end)
        except (KeyError, ValueError, RuntimeError, ArithmeticError) as error:
            observations[symbol] = dict(status='unavailable', reason=str(error))
    return observations


async def batch_products(call):
    response = await call('list_products', dict(contract_types=['perpetual_futures'],
                                                states=['live'], page_size=500))
    return [p for p in response['result'] if p['symbol'] in CRYPTO_DEMO_SYMBOLS
            and (p.get('underlying_asset') or {}).get('symbol') == p['symbol'][:-3]
            and p.get('trading_status') == 'operational']


async def preview_batch(call, signals, campaign, *, products=None, contracts=LEGACY_CONTRACTS):
    if campaign['blocked']:
        return dict(status='account_blocked', reasons=campaign['reasons'], entries=[])
    needed = next_batch_size(campaign['completed'])
    if needed == 0:
        return dict(status='target_reached', entries=[])
    if products is None:
        products = await batch_products(call)
    catalog = sorted({p['symbol'] for p in products})
    if len(catalog) < needed:
        return dict(status='insufficient_distinct_coins', minimum_distinct_symbols=needed,
                    catalog_coins=catalog, entries=[])
    wallet = (await call('get_wallet_balances', {}))['result']
    cash = next(row['available_balance'] for row in wallet if row['asset_symbol'] == 'USD')
    filters = {'contract_types':['perpetual_futures']}
    tickers = {ticker['symbol']: ticker for ticker in (await call('list_tickers', filters))['result']}
    now = time.time()
    needs_quote = [p['symbol'] for p in products if p['symbol'] in CRYPTO_DEMO_SYMBOLS
                   and not 0 <= now - float(tickers.get(p['symbol'], {}).get('timestamp', 0))/1e6 < 12]
    if needs_quote:
        responses = await asyncio.gather(*(call('get_ticker', {'symbol':symbol})
                                           for symbol in needs_quote), return_exceptions=True)
        for symbol, response in zip(needs_quote, responses):
            if isinstance(response, dict) and response['result']['symbol'] == symbol:
                tickers[symbol] = response['result']
    markets = [(product, tickers[product['symbol']], signals.get(product['symbol'], {'status':'unavailable'}))
               for product in products if product['symbol'] in CRYPTO_DEMO_SYMBOLS and product['symbol'] in tickers]
    batch = plan_batch(markets, time.time(), cash, campaign['daily_loss_usd'],
                       completed=campaign['completed'], contracts=contracts)
    if batch['status'] == 'planned':
        batch['expires_at'] = min(float(tickers[entry['symbol']]['timestamp']) / 1e6 + 15
                                  for entry in batch['entries'])
    return batch


async def preview(call, signals, campaign):
    """Resolve trade metadata and risk only for the latest eligible signals."""
    if campaign['blocked']:
        return dict(status='account_blocked', reasons=campaign.get('reasons', []))
    now = time.time()
    candidates = [symbol for symbol in SYMBOLS if signals.get(symbol, {}).get('status') == 'ready'
                  and 0 <= now - signals[symbol]['closed_at'] < INTERVAL]
    if not candidates:
        return dict(status='waiting')
    wallet = (await call('get_wallet_balances', {}))['result']
    cash = next(row['available_balance'] for row in wallet if row['asset_symbol'] == 'USD')
    reasons = {}
    for symbol in candidates:
        signal = signals[symbol]
        try:
            product = (await call('get_product', {'symbol':symbol}))['result']
            ticker = (await call('get_ticker', {'symbol':symbol}))['result']
            now = time.time()
            if not 0 <= now - signal['closed_at'] < INTERVAL:
                raise ValueError('Signal expired during preflight')
            if product['symbol'] != symbol or ticker['symbol'] != symbol:
                raise ValueError('Exchange symbol does not match the signal')
            proposal = plan(product, ticker, now, cash, campaign['daily_loss_usd'], 0)
        except (KeyError, ValueError, RuntimeError, ArithmeticError) as error:
            reasons[symbol] = str(error)
            continue
        return dict(status='planned', plan=proposal, signal=signal,
                    signal_id=f"{symbol}:{signal['closed_at']}",
                    expires_at=min(signal['closed_at'] + INTERVAL, ticker['timestamp']/1e6 + 15))
    return dict(status='risk_blocked', reasons=reasons)
