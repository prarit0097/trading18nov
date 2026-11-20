const host = process;
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const Library = require('./fmz-wasm-engine.cjs');
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname, name), 'utf8'));
const selection = host.argv.slice(2).map(value => Number(value));
assert.ok(selection.every(Number.isSafeInteger));
const receipt = path.join(__dirname, `native-trials${selection.length ? '-' + selection.join('-') : ''}.jsonl`);
const stop = 'FMZ replay exclusive boundary';

function run(trial) {
  const {id, item, feed, cfg} = trial;
  const bytes = fs.readFileSync(path.join(__dirname, feed.file));
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), feed.sha256);
  const raw = bytes.toString('utf8');
  const history = JSON.parse(raw);
  const meta = history.detail;
  const end = Date.parse(`${feed.end}T00:00:00+05:30`);
  const start = Date.parse(`${feed.start}T00:00:00+05:30`);
  let requests = 0;
  global.__offlineProbe = (text) => {
    const url = new URL(text), q = url.searchParams;
    assert.equal(url.origin + url.pathname, 'https://q.fmz.com/data/history');
    assert.equal(q.get('eid'), feed.eid);
    assert.equal(q.get('symbol'), feed.symbol);
    assert.equal(Number(q.get('period')), feed.base_seconds * 1000);
    const from = Number(q.get('from')), to = Number(q.get('to'));
    let selected = history;
    if (q.get('event') === 'fill') {
      const warmup = feed.warmup;
      assert.ok(warmup && warmup.from_epoch === from && warmup.to_epoch === to, 'Extended native warmup archive unavailable');
      const input = fs.readFileSync(path.join(__dirname, warmup.file));
      assert.equal(crypto.createHash('sha256').update(input).digest('hex'), warmup.sha256);
      selected = JSON.parse(input);
    } else {
      assert.equal(q.get('event'), 'feed');
      assert.ok(from === feed.from_epoch && to === feed.to_epoch);
    }
    assert.ok(selected.data[0][0] <= from * 1000 && selected.data.at(-1)[0] >= (to - feed.base_seconds) * 1000);
    requests++;
    return JSON.stringify({...selected, data: selected.data.filter(row => row[0] >= from * 1000 && row[0] <= to * 1000)});
  };
  const ctx = Library.VCtx({
    start: feed.start + ' 00:00:00', end: feed.end + ' 00:05:00',
    period: feed.period, basePeriod: feed.base,
    exchanges: [{eid: feed.eid, currency: feed.symbol, balance: cfg.balance, stocks: 0, fee: [cfg.fee*100, cfg.fee*100]}],
  });
  const {scope} = ctx;
  const exchange = scope.exchange;
  const sleep = scope.Sleep;
  let calls = 0, skipped = 0;
  let outcome;
  scope.Sleep = ms => {
    assert.ok(++calls <= 200000, 'Source polling exceeded the replay call limit');
    assert.ok(Number.isFinite(ms) && ms >= 0, 'Invalid source Sleep duration');
    if (scope.Date.now() + ms >= end - 10000) {
      const rest = Math.max(0, end - 10000 - scope.Date.now());
      if (rest) sleep(rest);
      throw stop;
    }
    sleep(ms);
  };
  try {
    assert.equal(exchange.GetTicker().Time, start);
    for (const [name, value] of Object.entries(item.args)) {
      assert.match(name, /^[A-Za-z_$][\w$]*$/);
      assert.ok(!(name in scope) && name !== 'constructor' && name !== 'prototype');
      scope[name] = value;
    }
    if (!exchange.GetMinStock) exchange.GetMinStock = () => meta.minQty;
    if (item.plotting) {
      scope.$ = {...scope.$};
      for (const name of ['PlotLine', 'PlotHLine', 'PlotDot', 'PlotFlag', 'PlotBar']) scope.$[name] = () => {};
    }
    for (const method of ['GetDepth', 'GetTrades', 'GetIndex', 'GetTickers', 'SetProxy', 'IO', 'Go']) {
      exchange[method] = () => { throw Error(`Missing source dependency ${method}`); };
    }
    if (cfg.records_gate_seconds) {
      assert.equal(cfg.records_gate_seconds, {42: 28800, 2515: 86400}[id]);
      const nativeRecords = exchange.GetRecords;
      let prior;
      exchange.GetRecords = seconds => {
        assert.equal(seconds, cfg.records_gate_seconds);
        if (prior !== undefined) {
          const delta = prior + seconds * 1000 - scope.Date.now();
          if (delta > 0) { skipped++; scope.Sleep(delta); }
        }
        const records = nativeRecords(seconds);
        prior = records.at(-1).Time;
        return records;
      };
    }
    let stopped = false;
    try {
      vm.runInNewContext(item.code + '\nif (typeof init === "function") init();\nmain();', scope, {
        timeout: 18000, filename: `catalogue-${id}.js`, contextCodeGeneration: {strings: false, wasm: false},
      });
    } catch (error) {
      if (error !== stop) throw error;
      stopped = true;
    }
    if (!stopped) {
      const rem = Math.max(0, end - 10000 - scope.Date.now());
      if (rem) sleep(rem);
    }
    const last = exchange.GetTicker();
    assert.ok(last.Time >= end - 60000 && last.Time <= end, 'Missing end-of-window account snapshot');
    const account = exchange.GetAccount();
    const orders = [];
    let since = start;
    for (let page = 0; page < 100; page++) {
      const subset = exchange.GetHistoryOrders(feed.symbol, since, 100);
      assert.ok(Array.isArray(subset) && subset.every(x => x.Time >= since && x.Time < end));
      orders.push(...subset);
      if (subset.length < 100) break;
      since = Math.max(...subset.map(x => x.Time)) + 1;
      assert.ok(page < 99, 'History page limit exceeded');
    }
    const resting = exchange.GetOrders();
    assert.ok(Array.isArray(resting));
    const identifiers = new Set(orders.map(x => x.Id));
    for (const order of resting) {
      if (!identifiers.has(order.Id)) orders.push(order);
    }
    assert.equal(new Set(orders.map(x => x.Id)).size, orders.length);
    outcome = {requests, calls, skipped, last, account, orders, resting: resting.length, endedEarly: !stopped};
  } finally {
    ctx.Join();
  }
  return outcome;
}

async function main() {
  await new Promise(resolve => setTimeout(resolve, 500));
  const only = new Set(selection);
  for (const trial of read('native-jobs.json')) {
    if (only.size && !only.has(trial.id)) continue;
    const identity = {id: trial.id, coin: trial.feed.coin, start: trial.feed.start};
    let report;
    try { report = {...identity, ...run(trial)}; }
    catch (error) { report = {...identity, reason: String(error).slice(0, 450)}; }
    fs.appendFileSync(receipt, JSON.stringify(report) + '\n');
  }
}

main().catch(error => {
  fs.writeFileSync(path.join(__dirname, 'native-worker-error.txt'), error.stack || String(error));
  host.exitCode = 1;
});
