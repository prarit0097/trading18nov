"""Execute the pinned Python LeeksReaper port with causal Binance spot order semantics."""
import argparse
from bisect import bisect_right
from collections import Counter
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).absolute().parent
US=1_000_000
BTC=100_000_000
PRICE=100
AMOUNT=BTC*PRICE
LOT=1000
CASH=D(10_000)


class Stop(BaseException):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def truncate(x,digits=4):
    return int((x+1/10**max(10,digits+5))*10**digits)/10**digits


class Broker:
    def __init__(self,market,mode):
        self.raw=market
        self.mode=mode
        self.start=market['begin']*US
        self.end=market['end']*US
        self.fee=D(str(mode['fee']))
        self.required=mode['volume']
        self.books=market['book']
        self.times=[x[1] for x in self.books]
        self.book=self.books[0]
        self.tape=market['tape']
        self.cursor=self.notified=0
        self.clock=self.start
        self.balance=CASH
        self.cash_hold=D(0)
        self.btc=self.btc_hold=0
        self.live={}
        self.orders={}
        self.hist=[]
        self.mark_changes=[]
        self.used={}
        self.peak=CASH
        self.dd=D(0)
        self.calls=Counter()
        self.advance(max(self.book[0]*US,self.tape[0][0]))

    def update_quote(self,at):
        k=bisect_right(self.times,at)-1
        assert k>=0
        current=self.books[k]
        if current is not self.book:
            self.book=current
            self.used={}

    def mark(self):
        bid=self.book[4][2]
        equity=self.balance+self.cash_hold+D((self.btc+self.btc_hold)*bid)/AMOUNT
        self.peak=max(self.peak,equity)
        self.dd=max(self.dd,(self.peak-equity)/self.peak)
        if not self.mark_changes or self.mark_changes[-1][1:]!=[bid,str(equity)]:
            self.mark_changes.append([self.clock,bid,str(equity)])

    def fill(self,o,n,price,t,liquidity,proof):
        traded=D(n*price)/AMOUNT
        cost=traded*self.fee
        if o.buy:
            if liquidity=='maker':
                self.cash_hold-=o.reserved
                self.balance+=o.reserved
                o.reserved=D(0)
            self.balance-=traded+cost
            self.btc+=n
        else:
            if liquidity=='maker':self.btc_hold-=n
            else:self.btc-=n
            self.balance+=traded-cost
        assert min(self.btc,self.balance,self.btc_hold,self.cash_hold)>=0
        o.deal+=n
        o.left-=n
        o.value+=traded
        if not o.left:o.status=1
        self.hist.append(['fill',t,o.oid,int(o.buy),n,price,liquidity,proof,str(cost)])

    def on_trade(self,row):
        eligible,_,_,ident,aggressor,px,size=row
        direction=not aggressor
        offers=sorted((o for o in self.live.values() if o.buy==direction and o.posted<eligible and
                       (px<o.price if direction else px>o.price)),key=lambda o:(-o.price if direction else o.price,o.oid))
        for o in offers:
            amount=min(size,self.required*o.left-o.witness_units)
            if not amount:break
            o.witness_units+=amount
            size-=amount
            o.witnesses.append([ident,amount])
            if o.witness_units==self.required*o.left:
                self.fill(o,o.left,o.price,eligible,'maker',o.witnesses)
                del self.live[o.oid]
            if not size:break

    def advance(self,target):
        end=min(self.end-1,target)
        while self.cursor<len(self.tape) and self.tape[self.cursor][0]<=end:
            row=self.tape[self.cursor]
            self.cursor+=1
            self.clock=row[0]
            self.on_trade(row)
            if self.clock>=self.book[1]:
                self.update_quote(self.clock)
                self.mark()
        self.clock=end
        self.update_quote(end)
        self.mark()
        if target>=self.end:raise Stop

    def receive(self,name):
        self.calls[name]+=1
        self.advance(self.clock+200_000)

    def submit(self,buy,rawprice,rawsize):
        self.receive('Buy' if buy else 'Sell')
        price=round(rawprice*PRICE)
        quantity=round(rawsize*BTC/LOT)*LOT
        due=D(price*quantity)/AMOUNT*(1+self.fee)
        if quantity<=0 or min(price,rawprice)<=0 or D(price*quantity)/AMOUNT<5 or (buy and due>self.balance) or (not buy and quantity>self.btc):
            self.hist.append(['reject',self.clock,int(buy),price,quantity,rawprice,rawsize])
            return None
        assert self.clock-self.book[1]<=10*US,(self.clock,self.book[1])
        oid=len(self.orders)+1
        o=SimpleNamespace(oid=oid,buy=buy,price=price,quantity=quantity,left=quantity,posted=self.clock,status=0,
                          reserved=D(0),witnesses=[],witness_units=0,deal=0,value=D(0))
        self.orders[oid]=o
        self.hist.append(['order',self.clock,oid,int(buy),price,quantity,rawprice,rawsize])
        side=0 if buy else 2
        levels=self.book[4]
        for px,n in zip(levels[side::4],levels[side+1::4],strict=True):
            if not px or (px>price if buy else px<price):break
            consumed=self.used.get((buy,px),0)
            amt=min(o.left,max(0,n-consumed))//LOT*LOT
            if amt:
                self.used[buy,px]=consumed+amt
                self.fill(o,amt,px,self.clock,'taker',[*self.book[1:4],consumed])
            if not o.left:break
        if o.left:
            if buy:
                o.reserved=D(o.left*price)/AMOUNT*(1+self.fee)
                self.balance-=o.reserved
                self.cash_hold+=o.reserved
                assert self.balance>=0
            else:
                self.btc-=o.left
                self.btc_hold+=o.left
                assert self.btc>=0
            self.live[oid]=o
        self.mark()
        return oid

    @staticmethod
    def show(o):
        return SimpleNamespace(Id=o.oid,Status=o.status,Price=o.price/PRICE,Amount=o.quantity/BTC,DealAmount=o.deal/BTC,
                               AvgPrice=float(o.value*BTC/o.deal) if o.deal else 0)

    def Buy(self,p,n):
        return self.submit(True,p,n)

    def Sell(self,p,n):
        return self.submit(False,p,n)

    def Sleep(self,ms):
        self.calls['Sleep']+=1
        self.advance(self.clock+int(ms*1000))

    def GetDepth(self):
        self.receive('GetDepth')
        row=self.book[4]
        sides=[]
        for direction in (0,2):
            sides.append([SimpleNamespace(Price=x/PRICE,Amount=q/BTC)
                          for x,q in zip(row[direction::4],row[direction+1::4],strict=True) if x and q])
        return SimpleNamespace(Asks=sides[0],Bids=sides[1])

    def GetTrades(self):
        self.receive('GetTrades')
        rows=sorted(self.tape[self.notified:self.cursor],key=lambda r:r[3])
        self.notified=self.cursor
        return [SimpleNamespace(Id=t[3],Time=t[1]//1000,Price=t[5]/PRICE,Amount=t[6]/BTC) for t in rows]

    def GetAccount(self):
        self.receive('GetAccount')
        return SimpleNamespace(Balance=float(self.balance),FrozenBalance=float(self.cash_hold),Stocks=self.btc/BTC,FrozenStocks=self.btc_hold/BTC)

    def CancelOrder(self,oid):
        self.receive('CancelOrder')
        o=self.live.pop(oid,None)
        if o is None:return False
        if o.buy:self.cash_hold-=o.reserved;self.balance+=o.reserved;o.reserved=D(0)
        else:self.btc_hold-=o.left;self.btc+=o.left
        o.status=2
        self.hist.append(['cancel',self.clock,oid])
        return True

    def GetOrder(self,oid):
        self.receive('GetOrder')
        return self.show(self.orders[oid])

    def GetOrders(self):
        self.receive('GetOrders')
        return [self.show(o) for o in self.live.values()]

    def receipt(self):
        bid=self.book[4][2]
        cash=self.balance+self.cash_hold
        ending=cash+D((self.btc+self.btc_hold)*bid)/AMOUNT
        if self.mark_changes[-1][0]!=self.clock:self.mark_changes.append([self.clock,bid,str(ending)])
        return {'style':self.mode,'start':self.start,'end':self.end,'first_book_us':self.books[0][1],'initial':str(CASH),
                'startMark':self.books[0][4][2],'trace':self.hist,'counts':dict(self.calls),'markChanges':self.mark_changes,
                'bidCents':bid,'marked':str(ending),'markedDrawdownRatio':str(self.dd),'cash':str(self.balance),
                'lockedCash':str(self.cash_hold),'inventory':self.btc,'lockedBTC':self.btc_hold,'pending':list(self.live)}


def execute(code,params,market,style):
    replay=Broker(market,style)
    def host_import(name,*_):
        assert name=='time'
        return SimpleNamespace(time=lambda:replay.clock/US)
    env={'__builtins__':{'__import__':host_import,'__build_class__':__build_class__,'len':len,'min':min,'max':max,'range':range},
         '__name__':'archived_fmz_python',**params,'exchange':replay,'Sleep':replay.Sleep,'_C':lambda fn,*a:fn(*a),
         '_N':truncate,'Log':lambda *a:None,'LogProfit':lambda *a:None,'LogStatus':lambda *a:None,
         'ORDER_STATE_PENDING':0,'ORDER_STATE_CANCELED':2}
    exec(code,env)
    try:
        env['main']()
    except Stop:
        pass
    else:
        raise AssertionError('archive returned before replay end')
    assert replay.clock==replay.end-1 and replay.cursor==len(replay.tape)
    return replay.receipt()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True)
    a=p.parse_args()
    src=(ROOT/'round46-5093-source.json').read_bytes()
    cfg=json.loads(src)
    raw=(ROOT/'round45-5094-input.json.gz').read_bytes()
    assert digest(raw)==cfg['market_sha256'] and digest(cfg['script'].encode())==cfg['source_sha256']
    market=json.loads(gzip.decompress(raw))
    code=compile(cfg['script'],'FMZ-5093.py','exec')
    styles=[{'name':'archived zero fee','fee':0,'volume':1},{'name':'strict double volume','fee':0,'volume':2},
            {'name':'0.1% per-side fee sensitivity','fee':.001,'volume':1}]
    rows=[execute(code,cfg['params'],market,s) for s in styles]
    output=json.dumps({'market_sha256':digest(raw),'source_fixture_sha256':digest(src),'worker_sha256':digest(Path(__file__).read_bytes()),
                       'results':rows},separators=(',',':')).encode()
    (ROOT/a.receipt).write_bytes(gzip.compress(output,mtime=0))


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round46-5093-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
