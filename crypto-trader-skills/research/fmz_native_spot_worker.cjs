const hostProcess = process;
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const Library = require('./fmz-wasm-engine.cjs');
const root = __dirname;
const receipt = path.join(root, 'spot-replay-paged.json');
const dates = JSON.parse(fs.readFileSync(path.join(root, 'spot-feed.json'), 'utf8'));
const sourceIds = [476, 597];
const fee = .00059;
function stamp(day) { return Date.parse(`${day}T00:00:00+05:30`); }
function runOne(id, market) {
  const raw = fs.readFileSync(path.join(root, market.file), 'utf8');
  const bars = JSON.parse(raw);
  const symbol = `${market.coin}_USDT`;
  const start = stamp(market.start);
  const end = stamp(market.end);
  let requests = 0;
  global.__offlineProbe = text => {
    const url = new URL(text);
    const q = url.searchParams;
    assert.equal(url.origin+url.pathname, 'https://q.fmz.com/data/history');
    assert.equal(q.get('eid'), 'Binance');
    assert.equal(q.get('event'), 'feed');
    assert.equal(q.get('period'), '300000');
    assert.equal(q.get('symbol'), symbol);
    assert.equal(Number(q.get('from')), start/1000 - 900000);
    assert.equal(Number(q.get('to')), end/1000+300);
    ++requests;
    return raw;
  };
  const ctx = Library.VCtx({start:market.start+' 00:00:00',end:market.end+' 00:05:00',period:'15m',basePeriod:'5m',exchanges:[{eid:'Binance',currency:symbol,balance:10000,stocks:0,fee:[fee*100,fee*100]}]});
  const scope = ctx.scope;
  const exchange = scope.exchange;
  assert.equal(exchange.GetTicker().Time, start);
  if (!exchange.GetMinStock) exchange.GetMinStock = () => bars.detail.minQty;
  const sleep = scope.Sleep;
  const stop = 'Public replay end';
  let calls = 0;
  scope.Sleep = ms => {
    assert.ok(++calls <= 100000, 'Sleep call limit exceeded');
    assert.ok(Number.isFinite(ms) && ms >= 0, 'Invalid source Sleep duration');
    if (scope.Date.now() + ms >= end - 10000) {
      const rest = Math.max(0, end - 10000 - scope.Date.now());
      if (rest) sleep(rest);
      throw stop;
    }
    sleep(ms);
  };
  const source = fs.readFileSync(path.join(root, 'candidate-source', `${id}.js`),'utf8');
  let reason;
  try { vm.runInNewContext(source+'\nmain();', scope, {timeout: 120000, filename:`catalogue-${id}.js`}); }
  catch(e) { if (e !== stop) reason = String(e).slice(0,300); }
  let last, orders, account, status;
  if (!reason) {
    last = exchange.GetTicker();
    account = exchange.GetAccount();
    orders = [];
    let since = start;
    for (let page = 0; page < 100; page++) {
      const subset = exchange.GetHistoryOrders(symbol, since, 100);
      assert.ok(Array.isArray(subset) && subset.every(x => x.Time >= since && x.Time < end));
      orders.push(...subset);
      if (subset.length < 100) break;
      since = Math.max(...subset.map(x => x.Time)) + 1;
      assert.ok(page < 99, 'History page limit exceeded');
    }
    const open = exchange.GetOrders();
    assert.ok(open.length === 0, 'Resting orders prevent a complete closed-order reconciliation');
    assert.ok(last.Time >= end-60000 && last.Time <= end, 'Missing end-of-window snapshot');
    assert.equal(new Set(orders.map(x=>x.Id)).size, orders.length);
  }
  try { const rawResult=JSON.parse(ctx.Join()); status=rawResult.Finished; }
  catch(e) { if (!reason) reason=String(e).slice(0,300); }
  return {id,coin:market.coin,period:market.start,requests,calls,orders,account,last,status,reason};
}
(async () => {
  await new Promise(r => setTimeout(r, 500));
  let rows=[];
  for (const id of sourceIds) for (const market of dates) {
    try { rows.push(runOne(id, market)); }
    catch(e) { rows.push({id, coin:market.coin, period:market.start, reason: String(e).slice(0,300)}); }
    fs.writeFileSync(receipt,JSON.stringify(rows,null,2)+'\n');
  }
})().catch(e => { fs.writeFileSync(receipt,JSON.stringify({reason:e.stack})+'\n'); hostProcess.exitCode=1; });
