import assert from 'node:assert/strict';
import test from 'node:test';
import { fundingEvidence } from '../crypto_skills/delta_candidate_funding.mjs';

const received = 1795120000200;
const start = 1795120000000;
const end = start + 300000;
const symbols = new Set(['BTCUSD']);
const message = {
  type: 'funding_rate', sy: 'BTCUSD', ts: start * 1000 + 100000,
  nfr: start * 1000 + 3600000000, fi: 28800, fr: 0.01,
};

test('public funding evidence retains the exact schedule and receipt time', () => {
  assert.deepEqual(fundingEvidence(message, received, start, end, symbols), {
    symbol: 'BTCUSD', observed_exchange_us: message.ts, received_utc_ms: received,
    next_realization_us: message.nfr, interval_seconds: 28800, observed_rate: 0.01,
  });
});

test('stale, out-of-window, foreign and elapsed funding messages stay unverified', () => {
  for (const invalid of [
    { ...message, sy: 'XRPUSD' },
    { ...message, nfr: null },
    { ...message, nfr: message.ts },
    { ...message, ts: (start - 1) * 1000 },
    { ...message, nfr: message.ts + 30000000000 },
    { ...message, fi: 0 },
  ]) {
    assert.equal(fundingEvidence(invalid, received, start, end, symbols), null);
  }
  assert.equal(fundingEvidence(message, received + 16000, start, end, symbols), null);
  assert.equal(fundingEvidence(message, end, start, end, symbols), null);
});
