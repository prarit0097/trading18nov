import sys, json, copy, datetime, tempfile, pathlib
ROOT=pathlib.Path(r'E:\coding\code\Trade\day-trader-skill')
sys.path.insert(0,str(ROOT/'tests'))
from _load import load
risk=load('trader-risk','check'); ticket=load('trader-broker','ticket'); entry=load('trader-entry','entry'); alerts=load('trader-alerts','alerts'); ex=load('trader-exit','exit'); tm=load('trader-timemachine','timemachine'); facts=load('trader-analyst','facts')
cfg=json.loads((ROOT/'trader-budget/config.example.json').read_text())
order=json.loads((ROOT/'tests/fixtures/trader-risk/orders-tsla.json').read_text())['orders'][0]
now=risk.parse_now('2026-10-19 10:15')
def check(o,**kw): return risk.check([o],cfg,now=now,**kw)
r=check(order)
print('1 SAME-DAY PASS: initial',r['results'][0]['verdict'],'fresh 16:05 check',risk.check([order],cfg,now=risk.parse_now('2026-10-19 16:05'))['results'][0]['verdict'],'broker status',ticket.status_of(order,r,{},'2026-10-19')[1])
o=copy.deepcopy(order); o['qty']='4'; o['take_profit_limit_price']='400'; o['plan']['target']=400; o['plan']['max_loss']=23.44
r=check(o,prices={'TSLA':366.48})
print('2 LOSS MISMATCH: risk',r['results'][0]['verdict'],r['results'][0]['max_loss'],'broker loss',ticket.max_loss(o)[0])
o2={'symbol':'KO','side':'buy','qty':'5','type':'market','time_in_force':'day','order_class':'bracket','stop_loss_stop_price':'95','take_profit_limit_price':'105','plan':{'entry':100,'max_loss':25}}
state={'orders':[{'date':'2026-10-19','status':'placed','symbol':'TSLA','side':'buy','kind':'entry','max_loss':ticket.max_loss(o)[0]}]}
c2=dict(cfg,max_daily_loss_usd=50)
print('2 DAILY CONSEQUENCE:',risk.check([o2],c2,state=state,now=now)['results'][0]['verdict'],'actual cumulative stop risk',32.64+25)
print('3 NO QUOTE OR ORDER AGE CHECK: old fixture checked next day',risk.check([order],cfg,now=risk.parse_now('2026-10-20 10:15'),price_times={})['results'][0]['verdict'])
for reply in ['yes buy 8 AAPL','yes buy 100 TSLA at 370.04']:
 print('4 CONSENT:',reply,'=>',ticket.parse_yes(reply,order,['TSLA'])[0])
d=json.loads((ROOT/'tests/fixtures/trader-entry/TSLA-2026-10-19-5m.json').read_text()); chart=entry.parse_chart(json.dumps(d),'TSLA'); missing=copy.deepcopy(chart); opening=min(b['t'] for b in chart['bars']); missing['bars']=[b for b in chart['bars'] if b['t']!=opening]
r=entry.evaluate(missing,now)
print('5 INCOMPLETE OR:',r['status'],'range',r['opening_range']['bars'],'of',r['opening_range']['of'],'complete',r['opening_range']['complete'])
day=datetime.date(2026,11,27); flat,note=ex.resolve_flat_by(day,None,cfg,datetime.time(10,15)); rules=alerts.rules_from_plan({'symbol':'TSLA','stop':95,'target':105,'flat_by':flat,'date':day.isoformat()}); status=alerts.market_status(alerts.parse_now('2026-11-27 10:00'))
print('6 EARLY CLOSE: planner flat_by',flat,'alert rings at',str(alerts.ring_time(rules[-1],status)))
plan=tm.normalize_plan(json.loads((ROOT/'tests/fixtures/trader-budget/plan-tsla.json').read_text())); import gzip
text=gzip.open(ROOT/'tests/fixtures/trader-timemachine/TSLA-60d5m.json.gz','rt').read(); doc=tm.time_machine(text,plan,tm.parse_now('2026-10-19 10:50'),replays=1)
print('7 SIMULATION HORIZON: plan flat_by',plan['flat_by'],'default simulation until',doc['mc']['until'])
with tempfile.TemporaryDirectory() as td:
 p=str(pathlib.Path(td)/'portfolio.json')
 ticket.apply_fill(p,cfg,'TSLA','buy',8,364.18,'2026-10-19'); pf=ticket.apply_fill(p,cfg,'TSLA','buy',8,364.18,'2026-10-19')
 print('8 REPLAYED FILL: same fill twice => shares',pf['positions'][0]['shares'],'cash',pf['cash'])
fs=[]
for s,e,v,fp in [('2026-01-01','2026-03-31',1,'Q1'),('2026-04-01','2026-06-30',1,'Q2'),('2026-07-01','2026-09-30',1,'Q3'),('2026-01-01','2026-12-31',3.2,'FY')]:
 fs.append({'start':s,'end':e,'val':v,'fy':2026,'fp':fp,'form':'10-K' if fp=='FY' else '10-Q','filed':'2027-02-01'})
print('9 Q4 EPS:',facts.quarterly(fs)['2026-12-31']['value'],'vs 0.5 for equal-length quarters if each quarter earns $100 and diluted shares are 100/100/100/200 (annual EPS=400/125=3.2)')
o={'symbol':'AAPL','side':'buy','notional':'NaN','type':'market','time_in_force':'day','plan':{'entry':100,'stop':99,'target':101}}
r=check(o)
print('10 NONFINITE NOTIONAL:',r['results'][0]['verdict'],'cash_after',r['cash_after'])

# A previously placed but unfilled different-symbol order is counted in limits, not cash reservation.
pending={'orders':[{'date':'2026-10-19','status':'placed','symbol':'KO','side':'buy','kind':'entry','max_loss':30,'qty':'30'}]}
next_order={'symbol':'AAPL','side':'buy','notional':'3000','type':'market','time_in_force':'day','plan':{'entry':100,'stop':99,'target':101}}
r=risk.check([next_order],cfg,state=pending,now=now)
print('11 OUTSTANDING ORDER CASH: unfilled KO commitment 3000, next AAPL 3000, budget 5000 =>',r['results'][0]['verdict'],'cash_after',r['cash_after'])
assert r['results'][0]['verdict']=='PASS' and r['cash_after']==2000
