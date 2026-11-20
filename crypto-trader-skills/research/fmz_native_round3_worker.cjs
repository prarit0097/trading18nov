const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const Library = require('./fmz-wasm-engine.cjs');

const root = __dirname;
const read = file => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
const unix = day => Date.parse(day + 'T00:00:00+05:30');
const selection = new Set(process.argv.slice(2).map(Number));
const receipt = path.join(root, 'round3-native-js-' + [...selection].join('-') + '.jsonl');
const stop = Symbol('end of replay');
const cache = new Map();

function openTape(spec) {
  if (!cache.has(spec.sha256)) {
    const bytes = fs.readFileSync(path.join(root, spec.file));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), spec.sha256);
    cache.set(spec.sha256, JSON.parse(bytes));
  }
  return cache.get(spec.sha256);
}

function replay({id, code, args, cfg, feed}) {
  const now = unix(feed.start), end = unix(feed.end);
  const spot = feed.eid !== 'Futures_Binance';
  const instrument = feed.coin + '_USDT' + (spot ? '' : '.swap');
  const source = openTape(feed.market);
  const requests = [];
  global.__offlineProbe = text => {
    const url = new URL(text);
    const q = url.searchParams;
    const symbol = q.get('symbol'), event = q.get('event');
    const from = Number(q.get('from')) * 1000, to = Number(q.get('to')) * 1000;
    assert.equal(url.origin + url.pathname, 'https://q.fmz.com/data/history');
    assert.equal(q.get('eid'), feed.eid);
    assert.equal(Number(q.get('period')), feed.step * 1000);
    assert.match(event, /^(feed|fill)$/);
    requests.push({event, symbol, from, to});
    const funding = symbol === feed.coin + '_USDT.funding';
    const index = symbol === feed.coin + '_USDT.index';
    assert.ok(symbol === instrument || (!spot && (funding || index) && event === 'feed'), text);
    const tape = funding ? openTape(feed.funding) : index ? openTape(feed.index) : source;
    if (!funding) {
      // FMZ queries can terminate on a partial base bar at the exclusive boundary.
      const step = feed.step * 1000;
      assert.ok(tape.data[0][0] <= from + step - 1 && tape.data.at(-1)[0] >= to - step, text);
    }
    return JSON.stringify({...tape, data: tape.data.filter(r => from <= r[0] && r[0] <= to)});
  };
  const ctx = Library.VCtx({
    start: feed.start + ' 00:00:00', end: feed.end + ' 00:05:00',
    basePeriod: feed.base, period: feed.period,
    exchanges: [{eid: feed.eid, currency: feed.coin + '_USDT',
      balance: cfg.balance, stocks: 0, fee: [cfg.fee * 100, cfg.fee * 100]}],
  });
  const {scope} = ctx;
  const exchange = scope.exchange;
  const sleep = scope.Sleep;
  const ticker = exchange.GetTicker;
  const records = exchange.GetRecords;
  let sleepCalls = 0, skipped = 0;
  scope.Sleep = ms => {
    assert.ok(++sleepCalls <= 6000000 && Number.isFinite(ms) && ms >= 0, 'Invalid source sleep or polling budget exceeded');
    const time = scope.Date.now();
    if (time + ms >= end - 10000) {
      if (time < end - 10000) sleep(end - 10000 - time);
      throw stop;
    }
    sleep(ms);
  };
  try {
    assert.ok(Math.abs(ticker().Time - now) <= feed.step * 1000, 'Start ticker outside first traded base candle');
    for (const [key, value] of Object.entries(args)) {
      assert.match(key, /^[A-Za-z_$][\w$]*$/);
      assert.ok(!(key in scope) && key !== 'prototype');
      scope[key] = value;
    }
    const endGuard = native => (...params) => {
      if (scope.Date.now() >= end - 10000) throw stop;
      return native(...params);
    };
    exchange.GetTicker = endGuard(ticker);
    exchange.GetRecords = endGuard(records);
    if (!exchange.GetMinStock) exchange.GetMinStock = () => source.detail.minQty;
    // Only selected source-level cosmetic compatibility aliases are installed.
    if (cfg.print) scope.print = scope.Log;
    if (cfg.gate) {
      let prior;
      exchange.GetRecords = seconds => {
        assert.equal(seconds, cfg.gate);
        if (prior !== undefined && prior + seconds * 1000 > scope.Date.now()) {
          skipped++;
          scope.Sleep(prior + seconds * 1000 - scope.Date.now());
        }
        const bars = records(seconds);
        prior = bars.at(-1).Time;
        return bars;
      };
    }
    for (const key of ['GetDepth', 'GetTrades', 'GetIndex', 'GetTickers', 'IO', 'Go', 'SetProxy']) {
      exchange[key] = () => { throw Error('Original venue inputs required by ' + key); };
    }
    let stopped = false;
    try {
      vm.runInNewContext(code + '\nif (typeof init === "function") init();\nmain();', scope, {
        timeout: cfg.timeout, filename: 'catalogue-' + id + '.js',
        contextCodeGeneration: {strings: false, wasm: false},
      });
    } catch (error) {
      if (error !== stop) throw error;
      stopped = true;
    }
    if (!stopped && scope.Date.now() < end - 10000) sleep(end - 10000 - scope.Date.now());
    const snapshotTime = scope.Date.now();
    const last = ticker();
    assert.ok(end - feed.step * 1000 <= last.Time && last.Time <= end, 'Missing end-of-window market snapshot ' + JSON.stringify({last: last.Time, clock: snapshotTime, end}));
    const account = exchange.GetAccount();
    const positions = spot ? [] : exchange.GetPosition();
    const resting = exchange.GetOrders();
    const endOrders = [];
    let since = now;
    for (let page = 0; page < 100; page++) {
      const orders = exchange.GetHistoryOrders(instrument, since, 100);
      assert.ok(Array.isArray(orders) && orders.every(o => since <= o.Time && o.Time < end));
      endOrders.push(...orders);
      if (orders.length < 100) break;
      since = Math.max(...orders.map(o => o.Time)) + 1;
      assert.ok(page < 99, 'Native order history exceeds supported pagination');
    }
    const seen = new Set(endOrders.map(o => o.Id));
    for (const order of resting) if (!seen.has(order.Id)) endOrders.push(order);
    assert.equal(new Set(endOrders.map(o => o.Id)).size, endOrders.length);
    return {last, snapshotTime, account, positions, orders: endOrders, resting: resting.length,
      requests, sleepCalls, skipped, endedEarly: !stopped};
  } finally {
    ctx.Join();
  }
}

async function main() {
  await new Promise(resolve => setTimeout(resolve, 500));
  for (const trial of read('round3-native-jobs.json')) {
    if (selection.size && !selection.has(trial.id)) continue;
    const id = {id: trial.id, coin: trial.feed.coin, start: trial.feed.start};
    let result;
    try { result = {...id, ...replay(trial)}; }
    catch (error) { result = {...id, reason: String(error).slice(0, 650)}; }
    fs.appendFileSync(receipt, JSON.stringify(result) + '\n');
  }
}

main().catch(error => {
  fs.writeFileSync(path.join(root, 'round3-native-js-error.txt'), error.stack || String(error));
  process.exitCode = 1;
});
