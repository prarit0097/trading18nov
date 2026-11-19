import { randomUUID } from 'node:crypto';
import { appendFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

const endpoint = 'wss://socket-ind-pub.testnet.deltaex.org';

export function fundingEvidence(message, receivedMs, startMs, endMs, symbols) {
  if (message?.type !== 'funding_rate' || !symbols.has(message.sy)) return null;
  const { sy: symbol, ts: exchangeUs, nfr: nextUs, fi: interval, fr: rate } = message;
  if (!Number.isSafeInteger(exchangeUs) || !Number.isSafeInteger(nextUs) ||
      !Number.isSafeInteger(interval) || interval <= 0 || !Number.isFinite(rate)) return null;
  const ageMs = receivedMs - exchangeUs / 1000;
  if (exchangeUs < startMs * 1000 || exchangeUs >= endMs * 1000 ||
      receivedMs < startMs || receivedMs >= endMs || ageMs < -2000 || ageMs > 15000 ||
      nextUs <= Math.max(exchangeUs, receivedMs * 1000) || nextUs - exchangeUs > interval * 1000000) return null;
  return {
    symbol, observed_exchange_us: exchangeUs, received_utc_ms: receivedMs,
    next_realization_us: nextUs, interval_seconds: interval, observed_rate: rate,
  };
}

function collectFunding({ start, end, symbols, stopped, record }) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(endpoint);
    const streamId = randomUUID();
    let lastEvidence = Date.now();
    let settled = false;

    function finish(error) {
      if (settled) return;
      settled = true;
      clearInterval(check);
      if (socket.readyState < WebSocket.CLOSING) socket.close();
      if (error) reject(error);
      else resolve();
    }

    const check = setInterval(() => {
      if (stopped() || Date.now() >= end || Date.now() - lastEvidence > 70000) finish();
    }, 1000);
    socket.addEventListener('open', () => socket.send(JSON.stringify({
      type: 'subscribe', payload: { channels: [{ name: 'funding_rate', symbols: [...symbols] }] },
    })));
    socket.addEventListener('message', event => {
      if (settled || stopped()) return;
      const received = Date.now();
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        console.error('Public funding stream sent an unreadable frame');
        finish();
        return;
      }
      try {
        if (message?.type === 'error') {
          console.error('Public funding subscription error');
          finish();
          return;
        }
        const row = fundingEvidence(message, received, start, end, symbols);
        if (row) {
          lastEvidence = received;
          record({ ...row, stream_id: streamId });
        }
      } catch (error) {
        finish(error);
      }
    });
    socket.addEventListener('close', () => finish());
    socket.addEventListener('error', () => finish());
  });
}

async function main([run, identityJson, mode, ...names]) {
  const identity = JSON.parse(identityJson);
  const smoke = mode === 'smoke';
  if (identity.environment !== 'india_testnet' || !names.length ||
      (mode !== 'record' && !smoke)) throw new Error('Expected public Delta India testnet inputs');
  const symbols = new Set(names);
  const start = smoke ? Date.now() : Date.parse(identity.start);
  const end = smoke ? start + 90000 : Date.parse(identity.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) throw new Error('Invalid funding capture window');
  const stopFile = join(run, 'STOP_CANDIDATE_FUNDING');
  const counts = Object.fromEntries(names.map(symbol => [symbol, 0]));
  const stopped = () => smoke ? Object.values(counts).every(count => count > 0) : existsSync(stopFile);
  const record = row => {
    counts[row.symbol]++;
    if (smoke) return;
    const utcDay = new Date(row.received_utc_ms).toISOString().slice(0, 10);
    const file = join(run, `four-ready-funding-${utcDay}.jsonl`);
    appendFileSync(file, JSON.stringify({ ...identity, ...row }) + '\n', 'utf8');
  };
  console.log(JSON.stringify({ mode, source: endpoint, start: new Date(start), end: new Date(end) }));
  while (!stopped() && Date.now() < end) {
    const remaining = start - Date.now();
    if (remaining > 0) await delay(Math.min(5000, remaining));
    else {
      await collectFunding({ start, end, symbols, stopped, record });
      if (!stopped() && Date.now() < end) await delay(5000);
    }
  }
  console.log(JSON.stringify({ counts }));
  if (smoke && !Object.values(counts).some(Boolean)) process.exitCode = 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
