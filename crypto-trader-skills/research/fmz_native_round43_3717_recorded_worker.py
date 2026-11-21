"""Run #3717's source on the first published day's causal top-25 book and signed spot prints."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).absolute().parent
SPEC=ROOT/'round42-3717-input.json.gz'
US=1_000_000
BTC=100_000_000
CENTS=100
LOT=1000
MAKER=D('.0006')
TAKER=D('.00075')
INITIAL=D(1_000_000)


class EndOfDay(BaseException):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def trunc_host(value, digits=4):
    assert digits>=0
    return int((value+1/10**max(10,digits+5))*10**digits)/10**digits


class Replay:
    def __init__(self, spec, multiple):
        self.start=spec['begin']*US
        self.stop=spec['end']*US
        self.book=spec['book']
        self.book_s=[r[0] for r in self.book]
        self.current=None
        self.used_book={}
        self.tape=spec['tape']
        self.offset=0
        self.multiple=multiple
        self.calls=Counter()
        self.available=INITIAL
        self.btc=0
        self.locked=D(0)
        self.locked_btc=0
        self.orders={}
        self.live={True:{}, False:{}}
        self.levels={True:[],False:[]}
        self.trace=[]
        self.time=self.start
        self.mark=0
        self.peak=INITIAL
        self.maximum_drawdown=D(0)
        self.marks=[]
        self.mark_minute=-1
        self.choose_book(self.book[0][0]*US)
        self.advance(self.book[0][0]*US-self.start)

    def choose_book(self, at):
        ix=bisect_right(self.book_s,at//US)-1
        assert ix>=0
        book=self.book[ix]
        if self.current is None or book[1]!=self.current[1]:
            self.current=book
            self.used_book={}
        assert book[1]<=at and 0<=at-book[1]<4*US, (at,book[:4])

    def equity(self):
        return self.available+self.locked+D((self.btc+self.locked_btc)*self.mark)/(BTC*CENTS)

    def record_mark(self, at):
        if not self.mark:
            return
        equity=self.equity()
        self.peak=max(self.peak,equity)
        self.maximum_drawdown=max(self.maximum_drawdown,(self.peak-equity)/self.peak)
        minute=at//(60*US)
        if minute!=self.mark_minute:
            self.mark_minute=minute
            self.marks.append([at,self.mark,str(equity)])

    def advance(self, dt):
        ceiling=min(self.stop-1,self.time+dt)
        while self.offset<len(self.tape) and self.tape[self.offset][0]<=ceiling:
            trade=self.tape[self.offset]
            self.mark=trade[2]
            self.trade_through(trade)
            self.offset+=1
            self.record_mark(trade[0])
        self.time=ceiling
        if ceiling==self.stop-1:
            raise EndOfDay

    def call(self,name):
        self.calls[name]+=1
        self.advance(200_000)

    def strict_eligible(self,buy, price):
        levels=self.levels[buy]
        return reversed(levels[bisect_right(levels,price):]) if buy else iter(levels[:bisect_left(levels,price)])

    def rest(self, o):
        buy,p=o['buy'],o['price']
        bucket=self.live[buy]
        if p not in bucket:
            at=bisect_left(self.levels[buy],p)
            self.levels[buy].insert(at,p)
            bucket[p]=[]
        bucket[p].append(o)
        if buy:
            reserve=D(p*o['left'])/(BTC*CENTS)*(1+TAKER)
            assert self.available>=reserve
            o['reserved']=reserve
            self.available-=reserve
            self.locked+=reserve
        else:
            assert self.btc>=o['left']
            self.btc-=o['left']
            self.locked_btc+=o['left']

    def remove_live(self,o):
        buy,p=o['buy'],o['price']
        orders=self.live[buy][p]
        orders.remove(o)
        if not orders:
            del self.live[buy][p]
            self.levels[buy].remove(p)

    def trade_through(self, row):
        when, num, px, qty, aggressive_buy, *_=row
        passive_buy=not aggressive_buy
        left=qty
        for level in self.strict_eligible(passive_buy,px):
            for order in tuple(self.live[passive_buy][level]):
                if when<=order['posted']:
                    continue
                required=self.multiple*order['left']-order['through']
                used=min(left,required)
                if not used:
                    return
                order['through']+=used
                order['witnesses'].append([num,used])
                left-=used
                if order['through']==self.multiple*order['left']:
                    self.fill(order,order['left'],level,when,'maker',order['witnesses'])
                    self.remove_live(order)
            if not left:
                return

    def fill(self, o, units, px, when, liquidity, execution):
        assert units>0 and units<=o['left']
        value=D(px*units)/(CENTS*BTC)
        fee=value*(MAKER if liquidity=='maker' else TAKER)
        if o['buy']:
            if liquidity=='maker':
                reserve=o['reserved']
                self.locked-=reserve
                self.available+=reserve
            self.btc+=units
            self.available-=value+fee
        else:
            if liquidity=='maker':
                self.locked_btc-=units
            else:
                self.btc-=units
            self.available+=value-fee
        assert self.btc>=0 and self.available>=0 and self.locked_btc>=0 and self.locked>=0
        o['left']-=units
        self.trace.append(['fill',when,o['id'],int(o['buy']),units,px,liquidity,execution,str(fee)])

    def execute(self,buy,limit,budget,order):
        self.choose_book(self.time)
        snap,eligible,venue,local,depth=self.current
        assert depth
        side=0 if buy else 2
        max_qty=order['left']
        for px, qty in zip(depth[side::4],depth[side+1::4],strict=True):
            if not px or (limit and (px>limit if buy else px<limit)):
                break
            held=self.used_book.get((buy,px),0)
            take=min(max_qty,max(0,qty-held))//LOT*LOT
            if budget is not None:
                cost=D(px)/(BTC*CENTS)*(1+TAKER)
                take=min(take,int(budget//cost)//LOT*LOT)
            if not take:
                continue
            self.used_book[(buy,px)]=held+take
            self.fill(order,take,px,self.time,'taker',[eligible,venue,local,held])
            max_qty-=take
            if budget is not None:
                budget-=cost*take
            if not max_qty or (budget is not None and budget<cost*LOT):
                break
        if budget is not None and max_qty:
            last_px=next(p for p in reversed(depth[side::4]) if p)
            assert budget<D(last_px*LOT)/(BTC*CENTS)*(1+TAKER),'market order exceeds available 25 levels'
            order['left']=0

    def submit(self,buy,price,quantity):
        self.call('Buy' if buy else 'Sell')
        assert quantity>0
        market=price==-1
        assert not market or buy
        limit=0 if market else int(D(str(price))*CENTS)
        lots=10**12 if market else int(D(str(quantity))*BTC)
        assert lots%LOT==0
        reserve=D(str(quantity)) if market else D(lots*limit)/(BTC*CENTS)*(1+TAKER)
        if (buy and self.available<reserve) or (not buy and self.btc<lots):
            self.trace.append(['rejected',self.time,int(buy),limit,quantity])
            return None
        oid=len(self.orders)+1
        o={'id':oid,'buy':buy,'price':limit,'left':lots,'posted':self.time,'through':0,'witnesses':[]}
        self.orders[oid]=o
        self.trace.append(['order',self.time,oid,int(buy),limit,quantity])
        self.execute(buy,limit,reserve if market else None,o)
        if o['left']:
            assert not market
            self.rest(o)
        self.record_mark(self.time)
        return oid

    def SetCurrency(self, market):
        assert market=='BTC_USDT'

    def SetPrecision(self, p, q):
        assert (p,q)==(2,5)

    def GetTicker(self):
        self.call('GetTicker')
        return {'Last':self.mark/CENTS}

    def GetDepth(self):
        self.call('GetDepth')
        self.choose_book(self.time)
        return {'Asks':[{'Price':self.current[4][0]/CENTS}]}

    def GetAccount(self):
        self.call('GetAccount')
        return {'Balance':float(self.available),'Stocks':self.btc/BTC,
                'FrozenBalance':float(self.locked),'FrozenStocks':self.locked_btc/BTC}

    def GetOrder(self, oid):
        self.call('GetOrder')
        return {'Status':int(not self.orders[oid]['left'])}

    def Buy(self,price,quantity):
        return self.submit(True,price,quantity)

    def Sell(self,price,quantity):
        return self.submit(False,price,quantity)

    def Sleep(self,ms):
        self.calls['Sleep']+=1
        self.advance(ms*1000)

    def receipt(self):
        return {'multiple':self.multiple,'begin':self.start,'first_book':self.book[0][:4],
                'end':self.stop,'trace':self.trace,'calls':dict(self.calls),'minute_marks':self.marks,
                'available_USDT':str(self.available),'frozen_USDT':str(self.locked),'free_BTC_units':self.btc,
                'locked_BTC_units':self.locked_btc,'ending_mark_cents':self.mark,'marked_USDT':str(self.equity()),
                'marked_drawdown_pct':str(self.maximum_drawdown*100),'observed_trade_rows':self.offset}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True)
    args=p.parse_args()
    raw=SPEC.read_bytes()
    spec=json.loads(gzip.decompress(raw))
    assert digest(spec['script'].encode())==spec['script_sha256']
    assert spec['settings']=={'eid':'Binance','currency':'BTC_USDT','balance':1_000_000,'stocks':0,'fee':[.06,.075]}
    code=compile(spec['script'],'FMZ-3717.py','exec')
    rows=[]
    for m in (1,2):
        s=Replay(spec,m)
        env={'__builtins__':{'int':int,'float':float,'dict':dict,'set':set,'min':min,'range':range,'__build_class__':__build_class__},
             '__name__':'archived_strategy','exchange':s,'Sleep':s.Sleep,'_N':trunc_host,**spec['params']}
        exec(code,env)
        try:
            env['main']()
        except EndOfDay:
            pass
        else:
            raise AssertionError('archived runtime stopped before the observed day ended')
        assert s.time==s.stop-1 and s.offset==len(s.tape)
        rows.append(s.receipt())
    report={'input_sha256':digest(raw),'worker_sha256':digest(Path(__file__).read_bytes()),'results':rows}
    out=json.dumps(report,separators=(',',':')).encode()+b'\n'
    (ROOT/args.receipt).write_bytes(gzip.compress(out,mtime=0))


if __name__=='__main__':
    try:
        main()
    except Exception:
        import traceback
        (ROOT/'round43-3717-recorded-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
