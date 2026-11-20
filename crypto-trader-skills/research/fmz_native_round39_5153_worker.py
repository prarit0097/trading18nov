"""Run unmodified #5153 Python on observed BTC signed prints and causal BBO depth."""
import gzip
import hashlib
import json
from collections import Counter
from decimal import Decimal as D, ROUND_HALF_UP, localcontext
from pathlib import Path

ROOT=Path(__file__).absolute().parent
TICK=200
CASH=D(2500)
LEASE=20
MAKER=D('.0002')
TAKER=D('.0004')
ZERO=D(0)


class Cutoff(BaseException):
    pass


class Record(dict):
    __getattr__=dict.__getitem__


def hash_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def num(value):
    return D(str(value))


def encode(value):
    return str(value) if isinstance(value,D) else value


def list_levels(raw):
    if isinstance(raw,list):
        return raw
    flat=list(map(int,raw.split(',')))
    assert len(flat)%2==0
    return list(zip(flat[0::2],flat[1::2],strict=True))


class Replay:
    def __init__(self,spec,trade_tape,multiple):
        self.spec=spec
        self.tape=trade_tape
        self.multiple=multiple
        self.at=self.begin=spec['begin_ms']
        self.end=spec['end_ms']
        self.funding=spec['funding']
        self.funding_at=self.funding['exchange_settlement_ms']*1000
        self.funding_seen=False
        self.offset=0
        self.q=[0,0]
        self.basis=[ZERO,ZERO]
        self.wallet=CASH
        self.min_initial_margin=CASH
        self.orders={}
        self.rest={}
        self.audit=[]
        self.case_calls=Counter()
        self.polls=[]
        self.last_open_ids=None
        self.last_ticker=None
        self.last_pos=None
        self.store={}
        self.side=None
        self.book_consumed={}

    def coordinates(self):
        return (self.at-self.begin)//TICK

    def mark(self):
        return num(self.spec['marks'][self.coordinates()][3])

    def unreal(self,side,price):
        return (D(self.q[side])*price/1000-self.basis[side])*(1 if side==0 else -1)

    def equity(self,price):
        return self.wallet+sum(self.unreal(i,price) for i in (0,1))

    def evaluate_risk(self):
        current=self.mark()
        cushion=self.equity(current)-D(sum(self.q))*current/(1000*LEASE)
        assert cushion>0, 'equity below initial margin line'
        self.min_initial_margin=min(self.min_initial_margin,cushion)

    def settle(self):
        rate=num(self.funding['rate'])
        mark=num(self.funding['prior_mark'][3])
        flows=[D(self.q[i])*mark*rate/1000*(-1 if i==0 else 1) for i in (0,1)]
        self.wallet+=sum(flows)
        self.funding_seen=True
        self.audit.append({'kind':'funding','t':self.at,'event_us':self.funding_at,'qty':[*self.q],'mark':mark,
                           'rate':rate,'cash_flows':flows,'wallet':self.wallet})

    def fill(self,o,price_notional,market_liquidity,event_us,proof):
        assert o['Status']==0
        i=o['side']
        qty=o['qty']
        price=price_notional*1000/qty
        fee=price_notional*(TAKER if market_liquidity=='taker' else MAKER)
        pnl=ZERO
        if o['Offset']:
            assert self.q[i]>=qty
            fraction=D(qty)/self.q[i]
            principal=self.basis[i]*fraction
            pnl=(price_notional-principal)*(1 if i==0 else -1)
            self.basis[i]-=principal
            self.q[i]-=qty
        else:
            self.basis[i]+=price_notional
            self.q[i]+=qty
        self.wallet+=pnl-fee
        o.update(Status=1,DealAmount=qty/1000,AvgPrice=float(price))
        self.rest.pop(o['Id'],None)
        self.audit.append({'kind':'fill','t':self.at,'event_us':event_us,'order_id':o['Id'],'liquidity':market_liquidity,
                          'avg':price,'value':price_notional,'fee':fee,'pnl':pnl,'proof':proof,'qty':[*self.q],
                          'basis':[*self.basis],'wallet':self.wallet})

    def print_trade(self,tick):
        t,id,price,size,buy,exchange,arrival=tick
        assert t==max(exchange,arrival)
        eligible=sorted((o for o in self.rest.values() if o['Time']*1000<t and (buy and o['Type']==1 and price>o['cents']
                         or not buy and o['Type']==0 and price<o['cents'])), key=lambda x:(x['cents'] if buy else -x['cents'],x['Id']))
        for o in eligible:
            take=min(size,o['needed_units']-o['aggressive_units'])
            assert take>0
            o['aggressive_units']+=take
            o['proof'].append([id,t,price,take,buy])
            size-=take
            if o['aggressive_units']==o['needed_units']:
                value=D(o['qty']*o['cents'])/100_000
                self.fill(o,value,'maker',t,o['proof'])
            if size==0:
                break

    def advance(self,name):
        if self.at>=self.end:
            raise Cutoff
        self.case_calls[name]+=1
        self.at+=TICK
        assert self.at<=self.end
        while self.offset<len(self.tape) and self.tape[self.offset][0]<=self.at*1000:
            print_row=self.tape[self.offset]; self.offset+=1
            if not self.funding_seen and self.funding_at<=print_row[0]:
                self.settle()
            if self.rest:
                self.print_trade(print_row)
        if not self.funding_seen and self.funding_at<=self.at*1000:
            self.settle()
        self.evaluate_risk()
        if self.at==self.end:
            raise Cutoff

    def _G(self,key,*v):
        assert key in ('buyp','sellp')
        if v:
            self.store[key]=v[0]
        self.audit.append({'kind':'key','t':self.at,'key':key,'write':bool(v),'value':self.store.get(key)})
        return self.store.get(key)

    def SetContractType(self,symbol):
        assert symbol=='swap'
        return Record(InstrumentID='BTCUSDT',LotTick=.001,PriceTick=.1)

    def SetMarginLevel(self,lever):
        assert lever==LEASE
        return True

    def GetCurrency(self):
        return 'BTC_USDT'

    def SetDirection(self,side):
        assert side in ('buy','sell','closebuy','closesell')
        self.side=side
        return True

    def GetTicker(self):
        self.advance('ticker')
        r=self.spec['quotes'][self.coordinates()]
        px=self.tape[self.offset-1][2] if self.offset else self.spec['marks'][self.coordinates()][2]
        self.last_ticker=[self.at,px]
        return Record(Last=px/100,Buy=r[2]/100,Sell=r[3]/100)

    def GetPosition(self):
        self.advance('position')
        values=[]
        mark=self.mark()
        for i,n in enumerate(self.q):
            if not n:continue
            values.append(Record(Type=i,Amount=n/1000,Price=float(self.basis[i]*1000/n),Margin=float(self.basis[i]/LEASE),
                                 Profit=float(self.unreal(i,mark)),MarginLevel=LEASE))
        self.last_pos=[self.at,[*self.q]]
        return values

    def GetAccount(self):
        self.advance('account')
        return Record(Balance=float(self.wallet-sum(self.basis)/LEASE),Equity=float(self.equity(self.mark())))

    def GetOrders(self):
        self.advance('orders')
        ids=sorted(self.rest)
        if ids!=self.last_open_ids:
            self.polls.append([self.at,ids,[self.rest[k]['Type'] for k in ids]])
            self.last_open_ids=ids
        keys=('Id','Time','Price','Type','Offset','Status','Amount','DealAmount','AvgPrice')
        return [Record({k:self.rest[v][k] for k in keys}) for v in ids]

    def CancelOrder(self,id,old):
        assert old.Id==id and old.Status==0
        self.advance('cancel')
        found=self.rest.pop(id,None)
        if found:found['Status']=2
        self.audit.append({'kind':'cancel','t':self.at,'order_id':id,'was_resting':found is not None})
        return found is not None

    def submit(self,api,limit,quantity):
        self.advance('submit')
        side,qty=self.side,int((num(quantity)*1000).to_integral_value(rounding=ROUND_HALF_UP))
        assert qty>0
        buy=api=='Buy'; assert buy==(side in ('buy','closesell'))
        offset=side.startswith('close')
        book_side=0 if side in ('buy','closebuy') else 1
        cents=0 if limit==-1 else int((num(limit)*10).to_integral_value(rounding=ROUND_HALF_UP))*10
        i=self.coordinates()
        received,exchange,asks,bids=self.spec['depth'][i]
        assert exchange<=received<=self.at*1000 and self.at*1000-received<=5_000_000
        quotes=self.spec['quotes'][i]
        asks,bids=list_levels(asks),list_levels(bids)
        assert [bids[0][0],asks[0][0],bids[0][1],asks[0][1]]==quotes[2:6]
        depth=asks if buy else bids
        marketable=cents==0 or (depth[0][0]<=cents if buy else depth[0][0]>=cents)
        oid=len(self.orders)+1
        order=Record(Id=oid,Time=self.at,Price=cents/100,Amount=qty/1000,Type=int(not buy),Offset=int(offset),Status=0,
                     DealAmount=0,AvgPrice=0,cents=cents,qty=qty,side=book_side,needed_units=qty*self.multiple,aggressive_units=0,proof=[])
        self.orders[oid]=order
        proof_context={'kind':'placement','t':self.at,'id':oid,'direction':side,'q':qty,'limit_cent':cents,'raw_limit':limit,
                       'requested_qty':quantity,'marketable':marketable,'placed_position':[*self.q],
                       'source_tick':self.last_ticker,'source_positions':self.last_pos}
        self.audit.append(proof_context)
        if offset:assert self.q[book_side]>=qty
        if marketable:
            if cents: assert (depth[0][0]<=cents if buy else depth[0][0]>=cents)
            prior=self.book_consumed.setdefault((received,buy),{})
            left=qty; cost=0; consumed=[]
            for p,n in depth:
                if cents and (p>cents if buy else p<cents):break
                used=prior.get(p,0)
                assert n>=used
                take=min(left,n-used)
                if take:
                    prior[p]=used+take;consumed.append([p,take]);left-=take;cost+=p*take
                if not left:break
            assert not left,'displayed allowed depth insufficient'
            value=D(cost)/100_000
            if not offset: self.require_open_collateral(value)
            self.fill(order,value,'taker',self.at*1000,{'snapshot_us':received,'venue_us':exchange,'side':consumed})
        else:
            if not offset: self.require_open_collateral(D(qty*cents)/100_000)
            self.rest[oid]=order
        return oid

    def require_open_collateral(self,value):
        reserved=sum(D(o['qty']*o['cents'])/100_000*(D(1)/LEASE+TAKER) for o in self.rest.values() if not o['Offset'])
        assert value>=5
        assert self.wallet-sum(self.basis)/LEASE-reserved>value*(D(1)/LEASE+TAKER)

    def Buy(self,limit,amount):
        return self.submit('Buy',limit,amount)

    def Sell(self,limit,amount):
        return self.submit('Sell',limit,amount)


def middle(code,options,point,tape,multiple):
    sim=Replay(point,tape,multiple)
    env={**options,'exchange':sim,'exchanges':[sim],'_G':sim._G,'_C':lambda call,*args:call(*args),
         'Log':lambda *args:None,'LogProfit':lambda *args:None,
         '__builtins__':{'len':len,'range':range,'float':float}}
    exec(code,env)
    try:env['main']()
    except Cutoff:pass
    else:raise AssertionError('archived infinite loop returned early')
    assert sim.at==sim.end and sim.funding_seen
    return {'multiple':multiple,'events':sim.audit,'pending_order_polls':sim.polls,'call_counts':dict(sim.case_calls),
            'minimum_buffer_USDT':sim.min_initial_margin,'consumed_tape_rows':sim.offset,
            'ending':{'clock':sim.at,'quote_mark':sim.mark(),'cash':sim.wallet,'eq':sim.equity(sim.mark()),
                      'quantities':sim.q,'basis':sim.basis,'resting':list(sim.rest), 'store':sim.store}}


def main():
    job=(ROOT/'round39-5153-job.json.gz').read_bytes(); book=(ROOT/'round35-197-full-input.json.gz').read_bytes()
    cfg=json.loads(gzip.decompress(job));data=json.loads(gzip.decompress(book));
    script=cfg['source_py'];assert hash_bytes(book)==cfg['books_sha256'] and hash_bytes(script.encode())==cfg['source_sha256']
    assert cfg['starting_cash_USDT']==CASH and cfg['fees_pct']==[0.02,0.04]
    code=compile(script,'FMZ-5153.py','exec')
    values=[]
    with localcontext() as ctx:
        ctx.prec=37
        for day,spec in data['scope'].items():
            for multiple in (1,2):
                trial=middle(code,cfg['settings'],spec,cfg['tapes'][day]['tape'],multiple)
                values.append({'day':day,**trial})
    result={'input_sha256':hash_bytes(job),'book_sha256':hash_bytes(book),'worker_sha256':hash_bytes(Path(__file__).read_bytes()),'results':values}
    (ROOT/'round39-5153-receipt.json').write_text(json.dumps(result,default=encode),encoding='utf-8')


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round39-5153-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
