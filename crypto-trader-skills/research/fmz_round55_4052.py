"""Verify all #4052 lower-interval indicators and 136 legal-grid execution events."""
from collections import defaultdict
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from math import fsum, isclose
from pathlib import Path
import sys
from research.fmz_round7_magnifier import aggregate, ledger_metrics, read, sha256, write
from research.fmz_round49_3749 import wilder

def cci(seq, n):
    out = []
    for j in range(n - 1, len(seq)):
        recent = seq[j - n + 1:j + 1]
        center = fsum(recent) / n
        mean_abs_dev = fsum((abs(x - center) for x in recent)) / n
        out.append((seq[j] - center) / (0.015 * mean_abs_dev) if mean_abs_dev else None)
    return [None] * (n - 1) + out

def indicators(d):
    out = {}
    for code, children, key in ((5, d['five'], 288), (15, aggregate(d['five'], 3), 96), (30, aggregate(d['five'], 6), 48), (60, d['hour'], 24)):
        close = [r[4] for r in children]
        cc = cci(close, 20)
        if code != 60:
            mom = wilder(close, 14)
            out[f'RSI{code}'] = mom[key - 1::key]
        out[f'CCI{code}'] = cc[key - 1::key]
    names = ['RSI5', 'RSI15', 'RSI30', 'CCI5', 'CCI15', 'CCI30']
    levels = [65, 72, 74, 190, 195, 200]
    out['Gate'] = [all((v is None or v < cut for v, cut in zip(row, levels, strict=True))) for row in zip(*(out[k] for k in names), strict=True)]
    return out
CAPITAL = D(50000)
WEIGHTS = tuple(map(D, ('.1303', '.1429', '.1719', '.2267', '.3280')))
STEP = D('.001')
FEE = D('.00075')
PRICE_DELTA = D('.2')
TAKE_PROFIT = D('1.014')

def level(v, tick, rounding):
    return (v / tick).to_integral_value(rounding=rounding) * tick

def causal(data, gate, tick, require_through=False):
    orders, trades, windows = ([], [], [])
    chart, five = (data['chart'], data['five'])
    assert len(gate) == len(chart)
    entries = []
    closing = None
    held = []
    prior = 0
    for i, (stamp, o, h, l, close, vol) in enumerate(chart):
        before = len(held)
        o, h, l, close = map(lambda a: D(str(a)), (o, h, l, close))
        bar = five[i * 288:(i + 1) * 288]
        candidates = []
        for name, lim, qty in entries:
            if l < lim or (not require_through and l == lim):
                candidates.append((name, lim, qty))
        close_possible = closing and (h > closing or (not require_through and h == closing))
        if candidates and close_possible:
            raise ValueError(('entry-exit-overlap', i, candidates, float(closing), held))
        if close_possible:
            p = max(o, closing)
            onset = next((z[0] for z in bar if D(str(z[2])) > closing or (not require_through and D(str(z[2])) == closing)))
            qty = sum((x[3] for x in held), D(0))
            assert qty > 0
            exe = {'id': 'exit_Long', 'barIndex': i, 'time': stamp, 'direction': 'strategy.exit', 'qty': float(qty), 'price': float(p)}
            orders.append(exe)
            windows.append((exe, onset))
            for name, t, entry, size in held:
                g = (p - entry) * size
                comm = (entry + p) * size * FEE
                trades.append({'id': name, 'entryTime': t, 'exitTime': stamp, 'entryPrice': float(entry), 'exitPrice': float(p), 'dir': 1, 'qty': float(size), 'gross': float(g), 'commission': float(comm), 'profit': float(g - comm)})
            closing = None
            held = []
        elif candidates:
            for name, limit, size in candidates:
                if size <= 0:
                    continue
                p = min(o, limit)
                onset = next((z[0] for z in bar if D(str(z[3])) < limit or (not require_through and D(str(z[3])) == limit)))
                held.append((name, stamp, p, size))
                exe = {'id': name, 'barIndex': i, 'time': stamp, 'direction': 'strategy.long', 'qty': float(size), 'price': float(p)}
                orders.append(exe)
                windows.append((exe, onset))
            consumed = {d[0] for d in candidates}
            entries = [e for e in entries if e[0] not in consumed]
        if held:
            if prior:
                avg = sum((x[2] * x[3] for x in held)) / sum((x[3] for x in held))
                closing = level(avg * TAKE_PROFIT, tick, ROUND_CEILING)
        elif before:
            assert closing is None
            entries = []
        elif gate[i]:
            for k, w in enumerate(WEIGHTS):
                val = close * (1 - k * PRICE_DELTA)
                quantity = CAPITAL * w / val // STEP * STEP
                item = (f'Long{k}', level(val, tick, ROUND_FLOOR), quantity)
                entries = [e for e in entries if e[0] != item[0]] + [item]
        prior = len(held)
    return (orders, trades, held, windows)

def normalized_native(broker):
    normal = []
    for e in broker['orders']:
        item = {**e, 'qty': e['qty'] / 1000}
        if normal and all((item[k] == normal[-1][k] for k in item if k != 'qty')) and (item['id'] == 'exit_Long'):
            normal[-1]['qty'] += item['qty']
        else:
            normal.append(item)
    return normal

def same_orders(a, b):
    assert len(a) == len(b), (len(a), len(b))
    for i, (x, y) in enumerate(zip(a, b, strict=True)):
        assert all((x[k] == y[k] or (k in ('qty', 'price') and isclose(x[k], y[k], abs_tol=1e-08, rel_tol=0)) for k in x)), (i, x, y)

def mark_data(data, orders, native):
    upcoming = defaultdict(list)
    for item in orders:
        upcoming[item['barIndex']].append(item)
    cash = D(50000)
    position = D(0)
    charged = D(0)
    peak = cash
    dd = D(0)
    at_risk = D(0)
    for i, row in enumerate(data['chart']):
        for e in upcoming[i]:
            size = D(str(e['qty']))
            price = D(str(e['price']))
            qty = size if e['direction'] == 'strategy.long' else -size
            cash -= qty * price
            position += qty
            charged += size * price * D('.00075')
        value = position * D(str(row[4]))
        eq = cash + value
        with_fee = eq - charged
        peak = max(peak, with_fee)
        dd = max(dd, peak - with_fee)
        at_risk = max(at_risk, value)
        for key, ex in (('cash', cash), ('marketValue', value), ('equity', eq)):
            assert isclose(native['equity'][i][key], float(ex), abs_tol=1e-07, rel_tol=0), (i, key, native['equity'][i][key], ex)
    return (float(cash), float(position), float(dd), float(with_fee), float(at_risk))


SOURCE='2ff4b968f45aae983caf4ed28bc68e27aba22fd5cb99e86de65d7fa0e7d72f72'
ENGINE='6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda'


def market_case(market,data,baseline,scored):
    assert baseline['literal']['error'].startswith('E_PARSE_EXPR:')
    native=baseline['relocated']
    assert native['broker']['orders']==baseline['reference_only']['broker']['orders']
    assert native['broker']['trades']==baseline['reference_only']['broker']['trades']
    assert scored['diagnostics']==scored['broker']['diagnostics']==[]
    raw_trace=dict(native['plots'])
    scored_trace=dict(scored['plots'])
    observed=indicators(data)
    for key,actual in observed.items():
        for trace in (raw_trace,scored_trace):
            assert all(a==b or (None not in (a,b) and isclose(a,b,abs_tol=1e-6,rel_tol=0))
                       for a,b in zip(actual,trace[key],strict=True)),(market,key)
    raw_ghost=native['broker']['position'][-1]
    if market=='ETHUSDT':
        assert 0<raw_ghost['size']<.001 and raw_trace['Life'][-1]==1
        assert raw_ghost['barIndex']==288
        assert len(native['broker']['trades'])==28
    else:
        assert raw_ghost['size']==0 and len(native['broker']['trades'])==34
    tick=D('.1') if market=='BTCUSDT' else D('.01')
    order,trade,terminal,witness=causal(data,observed['Gate'],tick,require_through=True)
    at_touch=causal(data,observed['Gate'],tick)
    assert (order,trade,terminal)==at_touch[:3]
    lookup={r[0]:r for r in data['five']}
    assert all(lookup[stamp][-1]>0 for _,stamp in witness)
    broker=scored['broker']
    same_orders(order,normalized_native(broker))
    for encoded,raw in zip(trade,broker['trades'],strict=True):
        assert all(encoded[k]==raw[k] for k in ('id','entryTime','exitTime'))
        assert all(isclose(encoded[k],raw[k],abs_tol=1e-8,rel_tol=0) for k in ('entryPrice','exitPrice'))
        assert encoded['qty']==raw['qty']/1000 and isclose(encoded['gross'],raw['profit'],abs_tol=1e-8,rel_tol=0)
    _,position,drawdown,marked,maximum_exposure=mark_data(data,order,broker)
    summary=[]
    for name,t,px,quantity in terminal:
        summary.append({'id':name,'time':t,'entry_usdt':float(px),'quantity':float(quantity),
                        'mark_usdt':data['chart'][-1][4],
                        'unrealized_gross':float((D(str(data['chart'][-1][4]))-px)*quantity)})
    return {'market':market,'orders':order,'trades':trade,'new_position_price_conditions':sum(observed['Gate']),
            'strict_trade_through_journal':witness,'finished_open':summary,'ending_quantity':position,
            'after_fee_daily_marked_equity':marked,'after_fee_marked_maximum_drawdown':drawdown,
            'maximum_marked_inventory_value':maximum_exposure,'literal_tail_position':raw_ghost,
            'literal_native_closed_lots':len(native['broker']['trades']),
            'corrected_five_minute_ohlc_records':data['changed_ohlc_5m']}


def main(work,out):
    assert sha256(work/'source-4052.md')==SOURCE
    assert sha256(work/'priced-runtime/pine_compat/pine_compat.pyd')==ENGINE
    feed_file=work/'4052-feed-corrected.json'
    baseline_file=work/'4052-full.json'
    scored_file=work/'4052-whole-grid.json'
    feed,baseline,scored=read(feed_file),read(baseline_file),read(scored_file)
    lot_control=read(work/'4052-lot-fixture.json')
    assert lot_control['1']['plots']['positions']==[0,2,1,1,1,1]
    assert lot_control['1000']['plots']['positions']==[0,2,0,0,1,1]
    assert 0<lot_control['1']['plots']['hold'][2]<.001
    assert lot_control['1000']['plots']['hold'][2]==0
    assert len(feed['markets']['BTCUSDT']['differences'])==2
    cases=[market_case(m,d,baseline[m],scored[m]['whole_lot_grid']) for m,d in feed['markets'].items()]
    assert [len(c['trades']) for c in cases]==[34,35]
    assert [len(c['orders']) for c in cases]==[67,69]
    isolation=read(work/'round3-isolation-python.json')
    assert set(isolation)=={'file_error','network_error'} and all(v[0]=='PermissionError' for v in isolation.values())
    attrs={'id':4052,'group':'FMZ Pine v5 · exact lots, legal ticks and lower interval proof',
           'exit':'Authored 1.4% take profit after confirmed hold, validated with strict trade-through',
           'period':'Binance USD-M · 2022-11-14 to 2023-11-20 UTC exclusive','interval':'1d',
           'archive_interval':'5m','currency':'USDT'}
    rows=[{**attrs,'market':c['market'],**ledger_metrics(c['trades'],50_000,len(c['finished_open']))} for c in cases]
    rows.append({**attrs,'market':'BTCUSDT + ETHUSDT',**ledger_metrics(
        [trade for c in cases for trade in c['trades']],100_000,sum(len(c['finished_open']) for c in cases))})
    write(out,{'schema':'FMZ #4052 independently reconciled whole-lot and legal-tick DCA replay',
               'source_url':'https://www.fmz.com/strategy/432802','source_revision':'7853bb2bf262c4567ac238d3552d97f0e50cb801',
               'source_sha256':SOURCE,'engine_sha256':ENGINE,'feed_sha256':sha256(feed_file),
               'native_baseline_sha256':sha256(baseline_file),'native_grid_sha256':sha256(scored_file),
               'market_receipts':feed['receipts'],'fee_overlay_per_side':float(FEE),
               'quantity_residual_fixture':lot_control,'isolation':isolation,'cases':cases,
               'coverage':[[4052,'Tested · exact lots and actual 5m trade-through',
                            'Source capital assignment is reflected in the declared 50,000 account. Exact venue lots eliminate a proven fractional residual. Legal tick prices, all lower indicators and all 136 grouped fills match the independent ledger, with one open ETH lot.']],
               'results':rows})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
