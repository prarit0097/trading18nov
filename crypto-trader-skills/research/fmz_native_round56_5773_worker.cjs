'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Module = require('node:module');
const { createHash } = require('node:crypto');
const { gunzipSync } = require('node:zlib');

const here = name => path.join(__dirname, name);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const document = fs.readFileSync(here('fmz-wasm-engine.cjs'));
const pinned = document.toString('utf8');
const marker = 'BaseCurrency:arr[0],BasePeriod:basePeriod,DepthDeep:5,';
assert.equal(pinned.split(marker).length, 2);
const patched = pinned.replace(marker, 'BaseCurrency:arr[0],BasePeriod:1000,DepthDeep:10,');
const adapted = new Module(here('fmz-wasm-engine.cjs'), module);
adapted.filename = here('fmz-wasm-engine.cjs');
adapted.paths = module.paths;
adapted._compile(patched, adapted.filename);
const engine = adapted.exports;
const mode = process.argv[2];
assert.ok(['literal', 'display', 'compatibility'].includes(mode));
const isCompatible = mode === 'compatibility';

function main() {
  const job = JSON.parse(gunzipSync(fs.readFileSync(here('r50-5773-pilot-input.json.gz'))));
  assert.equal(sha(job.source),job.source_sha256);
  const cases = [];
  for (const coin of ['BTC', 'ETH']) {
    const market = job.feeds[coin];
    const req = [];
    global.__offlineProbe = text => {
      const u = new URL(text);
      const q = u.searchParams;
      const span = [Number(q.get('from')) * 1000, Number(q.get('to')) * 1000];
      req.push([u.href, ...span]);
      assert.equal(u.origin + u.pathname, 'https://q.fmz.com/data/history');
      assert.equal(q.get('symbol'), coin + '_USDT.swap');
      assert.equal(q.get('eid'), 'Futures_Binance');
      assert.equal(q.get('period'), '1000');
      assert.equal(q.get('depth'), '10');
      assert.ok(market.data[0][0] < span[0] && market.data.at(-1)[0] > span[1]);
      const data = market.data.filter(row => row[0] >= span[0] && row[0] <= span[1]);
      assert.ok(data.some(r => r[1].length >= 10) && data.some(r => r[6].length > 0));
      return JSON.stringify({...market, data});
    };
    const stamp = unix => new Date(unix * 1000).toISOString().replace('T', ' ').slice(0, 19) + ' +0000';
    const ctx = engine.VCtx({
      start: stamp(job.start),
      end: stamp(job.end),
      period: '1m',
      basePeriod: '1m',
      exchanges: [{ eid: 'Futures_Binance', currency: coin + '_USDT', balance: 10000, stocks: 0, fee: [0.02, 0.05] }],
    });
    const scope = ctx.scope;
    const e = scope.exchange;
    const trail = [];
    const counts = {};
    for (const name of ['SetContractType', 'SetDirection', 'GetAccount', 'GetPosition', 'GetDepth', 'GetTrades', 'Buy', 'Sell', 'CancelOrder']) {
      const original = e[name];
      e[name] = (...args) => {
        const result = original(...args);
        counts[name] = (counts[name] || 0) + 1;
        if (counts[name] <= 3 || ['Buy','Sell','CancelOrder','SetDirection'].includes(name)) {
          const observed = name === 'GetTrades' ? result.length : name==='GetDepth' ? [result.Bids.length,result.Asks.length] : result;
          trail.push({ name, t: scope.Date.now(), args, result: observed });
        }
        return result;
      };
    }
    const helperChecks = {reduce: 0, max: 0, min: 0};
    if (isCompatible) {
      function extremum(name, items, fn) {
        assert.ok(items.length > 0 && items.every(Number.isFinite));
        helperChecks[name]++;
        return fn(...items);
      }
      scope._ = {
        reduce(items, callback, initial) {
          assert.ok(Array.isArray(items) && Number.isFinite(initial));
          assert.ok(items.every(trade => [trade.Id, trade.Time, trade.Price, trade.Amount].every(Number.isFinite)));
          helperChecks.reduce++;
          const result = items.reduce(callback, initial);
          assert.ok(Number.isFinite(result));
          return result;
        },
        max(items) { return extremum('max', items, Math.max); },
        min(items) { return extremum('min', items, Math.min); },
      };
    }
    Object.assign(scope, {
      burstThresholdPct: 0.0003,
      pendingLevel: 9,
      pricePrecision: 4,
      amountPrecision: 2,
      coverPendingLevel: 3,
      pendingAmount: 0.03,
    });
    let outcome;
    try {
      const field = 'account.Info.totalWalletBalance';
      assert.equal(job.source.split(field).length, 2);
      assert.ok(job.source.includes('LogProfit(parseFloat(' + field + '), account)'));
      const source = mode === 'literal' ? job.source : job.source.replace(field, 'account.Balance');
      vm.runInNewContext(source + '\nmain();', scope, { filename: 'FMZ-5773.js', timeout: 25000, contextCodeGeneration: { strings: false, wasm: false } });
      outcome = 'returned';
    } catch (error) {
      outcome = error === 'EOF' ? 'native end of backtest' : String(error.stack || error);
    }
    const sourceTime = scope.Date.now();
    const raw = ctx.Join();
    const summary = typeof raw === 'string' ? JSON.parse(raw) : raw;
    cases.push({ coin, outcome, sourceTime, req, trail, counts, summary, helperChecks });
  }
  fs.writeFileSync(here('r50-5773-' + mode + '.json'), JSON.stringify({ source: job.document_sha256, engine: sha(document), exact_adapter: marker, cases }));
}

setTimeout(() => {
  try { main(); }
  catch (error) {
    fs.writeFileSync(here('r50-5773-' + mode + '-error.txt'), String(error.stack || error));
    process.exitCode = 1;
  }
}, 500);
