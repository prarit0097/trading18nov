process.env.TZ = 'UTC';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {gunzipSync} = require('node:zlib');
const FMZ = require('./fmz-wasm-engine.cjs');

const STOP = Symbol('replay cutoff');
const STEP = 900000;
const SYMBOL = 'ETH_USDT.swap';
const time = t => new Date(t).toISOString().slice(0, 19).replace('T', ' ');
const read = f => fs.readFileSync(path.join(__dirname, f));
const write = (f, v) => fs.writeFileSync(path.join(__dirname, f), JSON.stringify(v));
const sha = b => createHash('sha256').update(b).digest('hex');
const quote = t => [t.Time, t.Last, t.Buy, t.Sell];

function session(job, spec) {
    const requests = [];
    global.__offlineProbe = uri => {
        const url = new URL(uri), query = url.searchParams;
        assert.equal(url.origin + url.pathname, 'https://q.fmz.com/data/history');
        const [coin, field] = query.get('symbol').split('.');
        assert.equal(coin, 'ETH_USDT');
        const market = spec.market[field];
        assert.ok(['swap', 'index', 'funding'].includes(field));
        assert.equal(query.get('eid'), 'Futures_Binance');
        assert.equal(Number(query.get('period')), STEP);
        const from = Number(query.get('from')) * 1000, to = Number(query.get('to')) * 1000;
        const data = market.data.filter(r => from <= r[0] && r[0] <= to);
        assert.ok(data.length);
        requests.push([field, query.get('event'), from, to, data.length]);
        return JSON.stringify({data, schema: market.schema, detail: market.detail});
    };
    const ctx = FMZ.VCtx({start: time(spec.begin), end: time(spec.end + STEP), period: '30m', basePeriod: '15m',
        exchanges: [{eid: 'Futures_Binance', currency: 'ETH_USDT', balance: job.starting_cash_USDT,
            stocks: 0, fee: job.fees_pct, lever: 10, slippage: 0}]});
    assert.equal(ctx.scope.Date.now(), spec.begin);
    return {ctx, scope: ctx.scope, requests};
}

function tape(job, spec) {
    const {scope, requests, ctx} = session(job, spec);
    const prices = [];
    try {
        while (!prices.length || prices.at(-1)[0] <= spec.end) {
            const ticker = scope.exchange.GetTicker();
            if (prices.at(-1)?.[0] !== ticker.Time) prices.push(quote(ticker));
            assert.ok(prices.length < 10000);
        }
        assert.equal(prices.at(-2)[0], spec.end);
        return {prices, requests};
    } finally { ctx.Join(); }
}

function replay(day, job, spec, tape) {
    const {scope, requests, ctx} = session(job, spec);
    const E = scope.exchange;
    const native = Object.fromEntries(['GetTicker', 'GetOrders', 'GetOrder', 'GetPosition', 'GetAccount',
        'GetHistoryOrders', 'Buy', 'Sell', 'SetDirection', 'CancelOrder'].map(k => [k, E[k]]));
    const sleep = scope.Sleep;
    const now = () => scope.Date.now();
    const put = [], changes = [], cancellations = [], observations = [];
    const orderSeenAt = new Map();
    let lastOrderPoll = null, lastPosition = [];
    const qIndex = new Map(tape.prices.map((r, i) => [r[0], i]));
    let direction = null, lastTicker = null, sleepCalls = 0, tickerCalls = 0;
    let previousWallet = job.starting_cash_USDT, previousAccountCall = spec.begin;
    function guard() { if (now() >= spec.end) throw STOP; }
    E.GetTicker = () => {
        guard();
        tickerCalls++;
        // Last source read may advance the broker to the next quote. The independent tape includes the cutoff tick.
        const index = lastTicker && qIndex.get(lastTicker[0]);
        if (index !== null) assert.ok(index < tape.prices.length - 1);
        const got = native.GetTicker();
        lastTicker = quote(got);
        assert.deepEqual(lastTicker, tape.prices[qIndex.get(got.Time)]);
        assert.ok(now() <= spec.end, 'source ticker crossed cutoff');
        if (now() === spec.end) throw STOP;
        return got;
    };
    E.GetOrders = () => {
        guard();
        const before = now();
        const open = native.GetOrders();
        const polled = open.map(o => o.Id);
        if (!lastOrderPoll || lastOrderPoll.open.join(',') !== polled.join(',')) {
            const unseen = lastOrderPoll ? lastOrderPoll.open.filter(id => !polled.includes(id)) : [];
            changes.push({before, after: now(), open, unseen: unseen.map(id => [id, orderSeenAt.get(id)])});
        }
        for (const id of polled) orderSeenAt.set(id, now());
        lastOrderPoll = {time: now(), open: polled};
        return open;
    };
    E.GetPosition = () => { guard(); lastPosition = native.GetPosition(); return lastPosition; };
    E.GetAccount = () => {
        guard();
        const out = native.GetAccount();
        const wallet = out.Equity - out.UPnL;
        if (Math.abs(wallet - previousWallet) > 1e-9) {
            previousWallet = wallet;
            observations.push({at: now(), previous_account_ms: previousAccountCall, wallet, account: out, positions: lastPosition});
        }
        previousAccountCall = now();
        return out;
    };
    E.SetDirection = d => {guard(); direction = d; return native.SetDirection(d); };
    for (const side of ['Buy', 'Sell']) E[side] = (limit, size) => {
        guard();
        const start = now();
        const id = native[side](limit, size);
        put.push({id, side, direction, limit, size, ticker: lastTicker, start, end: now()});
        return id;
    };
    E.CancelOrder = (id, ...args) => {
        guard();
        const before = now();
        const result = native.CancelOrder(id, ...args);
        cancellations.push({id, before, after: now(), result});
        return result;
    };
    scope.Sleep = ms => {
        guard();
        assert.ok(++sleepCalls < 35000 && [100, 5000].includes(ms));
        const until = Math.min(now() + ms, spec.end);
        sleep(until - now());
        assert.equal(now(), until);
        if (now() === spec.end) throw STOP;
    };
    for (const [k, v] of Object.entries(job.parameters)) {
        assert.ok(!(k in scope)); scope[k] = v;
    }
    scope.LogStatus = () => {};
    scope.LogProfit = () => {};
    try {
        try {
            const context = vm.createContext(scope, {codeGeneration: {strings: false, wasm: false}});
            vm.runInContext(job.source + '\nmain();', context, {timeout: 120000, filename: 'FMZ-4899.js'});
            assert.fail('archived loop returned early');
        } catch (error) { if (error !== STOP) throw error; }
        assert.equal(now(), spec.end);
        const account = native.GetAccount();
        const terminalAccount = {at:now(), previous_account_ms:previousAccountCall};
        const positions = native.GetPosition();
        const pending = native.GetOrders();
        assert.ok(now() < tape.prices.at(-1)[0], 'account mark passed the next quote');
        const history = [];
        for (let since = spec.begin, page = 0; page < 100; page++) {
            const batch = native.GetHistoryOrders(SYMBOL, since, 100);
            assert.ok(Array.isArray(batch)); history.push(...batch);
            if (batch.length < 100) break;
            since = Math.max(...batch.map(o => o.Time)) + 1;
            assert.ok(page < 99);
        }
        assert.equal(new Set(put.map(x => x.id).filter(Boolean)).size, history.length + pending.length);
        return {day, put, changes, cancellations, observations, requests, account, positions, pending, history, terminalAccount,
            ticker: tape.prices.at(-2), checked_clock_ms: now(), stop_ms: spec.end, counts: {sleepCalls, tickerCalls}};
    } finally { ctx.Join(); }
}

(async () => {
    await new Promise(resolve => setTimeout(resolve, 500));
    const input = read('round33-4899-input.json.gz');
    const job = JSON.parse(gunzipSync(input));
    assert.equal(sha(job.source), job.source_sha256);
    const windows = [];
    for (const [day, spec] of Object.entries(job.scope)) {
        try {
            const chart = tape(job, spec);
            const model = replay(day, job, spec, chart);
            windows.push({chart, model});
        } catch (e) { throw Error(day + ' ' + (e.stack || e)); }
    }
    write('round33-4899-receipt.json',{input_sha256: sha(input), source_sha256: job.source_sha256,
        engine_sha256: sha(read('fmz-wasm-engine.cjs')), windows});
})().catch(err => { write('round33-4899-error.json', String(err.stack || err)); process.exitCode = 1; });
