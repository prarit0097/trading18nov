"""Explicit-unit closed-bar ingestion; public market-data-only Binance reads."""
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .core import SkillError, Workspace, decimal, utc, iso, require

BASE = 'https://data-api.binance.vision'
INTERVALS = {'1m': 60, '5m': 300, '15m': 900}
MAX_BODY = 4 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SkillError('Market-data redirects are not allowed')


def _get_json(path, params):
    require(path in ('/api/v3/exchangeInfo', '/api/v3/klines', '/api/v3/ticker/bookTicker'),
            'Only public market-data endpoints are permitted')
    try:
        req = Request(BASE + path + '?' + urlencode(params), headers={'User-Agent':'crypto-skills/1'})
        with build_opener(_NoRedirect()).open(req, timeout=10) as response:
            body = response.read(MAX_BODY + 1)
        require(len(body) <= MAX_BODY, 'Market response exceeds 4MiB')
        return json.loads(body)
    except (OSError, ValueError) as exc:
        raise SkillError(f'Public market data failed: {exc}') from exc


def validate_market(raw, config, now=None):
    """Validate imported data without guessing bar status, currency or volume units."""
    require(isinstance(raw, dict), 'Market must be a JSON object')
    for key in ('symbol', 'venue', 'product_type'):
        require(raw.get(key) == config.get(key), f'Market {key} does not match config')
    require(raw['product_type'] in ('spot', 'linear_perpetual'), 'Unknown product type')
    step = raw.get('interval_seconds')
    require(type(step) is int and step in INTERVALS.values(), 'Unsupported interval_seconds')
    asof = utc(raw.get('as_of')) if raw.get('as_of') is not None else None
    require(asof is not None, 'Missing market as_of')
    current = utc(now)
    age = (current - asof).total_seconds()
    max_age = decimal(config.get('max_market_age_seconds', 120))
    require(max_age > 0 and 0 <= age <= max_age, 'Market snapshot is stale or future dated')
    source = raw.get('source')
    require(isinstance(source, dict) and source.get('mode') in ('fixture','import','public_rest'),
            'Missing or unknown market provenance')
    quote = config.get('quote_currency')
    base = source.get('volume_unit')
    require(isinstance(quote,str) and quote and source.get('price_unit') == quote,
            'Missing or incompatible price unit')
    require(isinstance(base,str) and base and re.fullmatch(r'[A-Z0-9]{1,20}',base)
            and base + quote == raw['symbol'], 'Missing or incompatible base-volume unit')
    metadata = raw.get('metadata')
    require(isinstance(metadata,dict), 'Missing market filters')
    filters = {}
    for key in ('qty_step','price_tick','min_notional'):
        value = decimal(metadata.get(key))
        require(value > 0, f'Invalid {key}')
        filters[key] = str(value)
    bid, ask = decimal(raw.get('bid')), decimal(raw.get('ask'))
    require(0 < bid <= ask, 'Invalid bid/ask spread')
    bars = raw.get('bars')
    require(isinstance(bars,list) and 1 <= len(bars) <= 1000, 'Expected 1..1000 closed bars')
    cleaned = []
    previous = None
    for bar in bars:
        require(isinstance(bar,dict) and bar.get('closed') is True, 'Only explicitly closed bars are valid')
        require(bar.get('time') is not None, 'Missing bar open time')
        opened = utc(bar['time'])
        require(opened.microsecond == 0 and int(opened.timestamp()) % step == 0,
                'Bar time is not interval aligned')
        require(opened + timedelta(seconds=step) <= asof, 'Unclosed or future bar')
        if previous is not None:
            require((opened-previous).total_seconds() == step, 'Duplicate, unordered or gapped bars')
        previous = opened
        prices = {key: decimal(bar.get(key)) for key in ('open','high','low','close','volume')}
        require(min(prices[k] for k in ('open','high','low','close')) > 0, 'Nonpositive OHLC price')
        require(prices['low'] <= min(prices['open'],prices['close'])
                <= max(prices['open'],prices['close']) <= prices['high'], 'Invalid OHLC relationships')
        require(prices['volume'] >= 0, 'Negative base volume')
        cleaned.append(dict(time=iso(opened),closed=True,**{k:str(v) for k,v in prices.items()}))
    require((asof - previous).total_seconds() < 2 * step, 'Last closed bar is stale')
    return dict(symbol=raw['symbol'],venue=raw['venue'],product_type=raw['product_type'],
                interval_seconds=step,as_of=iso(asof),bars=cleaned,bid=str(bid),ask=str(ask),
                metadata=filters,health=dict(valid=True,gaps=[],closed_bars=len(cleaned)),source=source)


def fetch_market(config, symbol, interval, limit, now=None):
    require(config.get('venue') == 'binance' and config.get('product_type') == 'spot',
            'Public REST collector supports Binance spot only')
    require(isinstance(symbol,str) and re.fullmatch(r'[A-Z0-9]{5,30}',symbol)
            and symbol == config.get('symbol'), 'Fetch symbol must match config')
    require(interval in INTERVALS, 'Unsupported interval')
    require(type(limit) is int and 2 <= limit <= 1000, 'Market limit must be 2..1000')
    current = utc(now)
    info = _get_json('/api/v3/exchangeInfo',dict(symbol=symbol))
    require(isinstance(info,dict) and len(info.get('symbols',[])) == 1,'Missing exchange symbol metadata')
    item = info['symbols'][0]
    require(item.get('symbol') == symbol and item.get('status') == 'TRADING', 'Symbol is not trading')
    filters = {f.get('filterType'):f for f in item.get('filters',[]) if isinstance(f,dict)}
    meta = dict(qty_step=filters.get('LOT_SIZE',{}).get('stepSize'),
                price_tick=filters.get('PRICE_FILTER',{}).get('tickSize'),
                min_notional=filters.get('NOTIONAL',filters.get('MIN_NOTIONAL',{})).get('minNotional'))
    rows = _get_json('/api/v3/klines',dict(symbol=symbol,interval=interval,limit=limit))
    require(isinstance(rows,list) and len(rows) <= limit, 'Invalid kline response')
    bars=[]
    for row in rows:
        require(isinstance(row,list) and len(row) >= 7 and type(row[0]) is int
                and type(row[6]) is int, 'Invalid Binance kline')
        opened=datetime.fromtimestamp(row[0]/1000,timezone.utc)
        require(row[6] == row[0]+INTERVALS[interval]*1000-1,'Unexpected Binance close time')
        if opened + timedelta(seconds=INTERVALS[interval]) > current:
            require(opened <= current, 'Future Binance kline')
            continue
        bars.append(dict(time=iso(opened),open=row[1],high=row[2],low=row[3],close=row[4],volume=row[5],closed=True))
    quote = _get_json('/api/v3/ticker/bookTicker',dict(symbol=symbol))
    require(isinstance(quote,dict) and quote.get('symbol') == symbol, 'Invalid quote symbol')
    raw=dict(symbol=symbol,venue='binance',product_type='spot',interval_seconds=INTERVALS[interval],
             as_of=iso(current),bars=bars,bid=quote.get('bidPrice'),ask=quote.get('askPrice'),metadata=meta,
             source=dict(mode='public_rest',base_url=BASE,price_unit=item.get('quoteAsset'),
                         volume_unit=item.get('baseAsset'),retrieved_at=iso(current)))
    return validate_market(raw,config,current)


def run(args):
    w=Workspace(args.workspace)
    current=utc(getattr(args,'now',None))
    with w.lock():
        try:
            config=w.config
            require(bool(getattr(args,'input',None)) != bool(getattr(args,'fetch',False)),
                    'Specify exactly one of --input or --fetch')
            if getattr(args,'fetch',False):
                data=fetch_market(config,getattr(args,'symbol',None) or config.get('symbol'),
                                  getattr(args,'interval','1m') or '1m',getattr(args,'limit',100),current)
            else:
                path=Path(args.input)
                require(path.stat().st_size <= MAX_BODY,'Market import exceeds 4MiB')
                raw=json.loads(path.read_text(encoding='utf-8'))
                data=validate_market(raw,config,current)
                data['source']=dict(data['source'],mode='import',path=str(path.resolve()))
            return w.write('market',data,inputs={'config':w.read('config')['digest']},now=current)
        except (SkillError,OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
            w.write('market',dict(health=dict(valid=False,gaps=[],closed_bars=0),error=str(exc),
                                  as_of=iso(current),source=dict(mode='import' if getattr(args,'input',None) else 'public_rest')),
                    now=current)
            raise SkillError(f'Market refresh failed; previous market invalidated: {exc}') from exc
