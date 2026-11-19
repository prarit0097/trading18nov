import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, renameSync, statfsSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const endpoint = 'wss://socket-ind-pub.testnet.deltaex.org';
const segmentMs = 300000;
const reserveBytes = 4 * 1024 ** 3;
const kinds = ['mark', 'book', 'candle'];

function quotedNumber(value) {
  return (typeof value === 'number' || typeof value === 'string' && value.trim() !== '') &&
    Number.isFinite(Number(value));
}

function positive(value) {
  return quotedNumber(value) && Number(value) > 0;
}

function level(value) {
  return Array.isArray(value) && value.length === 2 && positive(value[0]) &&
    quotedNumber(value[1]) && Number.isSafeInteger(Number(value[1])) && Number(value[1]) >= 0;
}

export function marketRow(event, receiptMs, startMs, endMs, symbols) {
  const { type, sy, ts } = event ?? {};
  if (!Number.isSafeInteger(ts) || !Number.isSafeInteger(receiptMs) ||
      ts < startMs * 1000 || ts >= endMs * 1000 || receiptMs < startMs || receiptMs >= endMs) return null;
  const age = receiptMs - ts / 1000;
  if (age < -2000 || age > 3000 || typeof sy !== 'string') return null;
  const symbol = symbols.indexOf(type === 'ob_l2' ? sy : sy.startsWith('MARK:') ? sy.slice(5) : '');
  if (symbol < 0) return null;
  const stamp = [symbol, ts, receiptMs];
  if (type === 'mark_price' && positive(event.p)) return ['mark', ...stamp, event.p];

  if (type === 'ob_l2') {
    const bids = Array.isArray(event.b) ? event.b.slice(0,5) : [];
    const ask = Array.isArray(event.a) ? event.a[0] : null;
    if (!Number.isSafeInteger(event.lts) || event.lts <= 0 || event.lts > ts ||
        !bids.length || !bids.every(level) || !level(ask) ||
        bids.some((item,i) => i && Number(bids[i-1][0]) <= Number(item[0])) ||
        Number(bids[0][0]) > Number(ask[0])) return null;
    return ['book', ...stamp, event.lts, bids, ask];
  }

  if (type === 'candlestick_1m') {
    const values = [event.o, event.h, event.l, event.c];
    if (Number.isSafeInteger(event.cst) && event.cst > 0 && event.cst <= ts &&
        event.cst % 60000000 === 0 && values.every(positive) &&
        Number(event.l) <= Math.min(Number(event.o),Number(event.c)) &&
        Math.max(Number(event.o),Number(event.c)) <= Number(event.h)) return ['candle', ...stamp, event.cst, ...values];
  }
  return null;
}

export function writeChunk(directory, header, rows) {
  const name = `${header.first_receipt_ms}-${randomUUID()}.jsonl.gz`;
  const target = join(directory, name);
  const staging = target + '.partial';
  const payload = gzipSync([header,...rows].map(row => JSON.stringify(row)).join('\n')+'\n');
  writeFileSync(staging,payload,{flag:'wx'});
  renameSync(staging,target);
  return target;
}

function archiveStream(run, identity, symbols, streamId) {
  let rows = [];
  function flush() {
    if (!rows.length) return;
    const first = rows[0][3];
    const day = new Date(first).toISOString().slice(0,10);
    const directory = join(run,'protective-quotes',day);
    mkdirSync(directory,{recursive:true});
    const volume = statfsSync(directory);
    if (volume.bavail * volume.bsize < reserveBytes) {
      throw new Error('Insufficient free disk space for protective quote archive');
    }
    writeChunk(directory,{schema:1,identity,symbols,stream_id:streamId,first_receipt_ms:first},rows);
    rows = [];
  }
  return {
    add(row) {
      if (rows.length && Math.floor(rows[0][3]/segmentMs) !== Math.floor(row[3]/segmentMs)) flush();
      rows.push(row);
    },
    flush,
  };
}

function collect({ start, end, symbols, stopped, makeWriter, counts }) {
  return new Promise((resolve,reject) => {
    const writer = makeWriter(randomUUID());
    const socket = new WebSocket(endpoint);
    let lastUpdate = Date.now();
    let finished = false;

    function finish(error) {
      if (finished) return;
      finished = true;
      clearInterval(check);
      if (socket.readyState < WebSocket.CLOSING) socket.close();
      if (error) return reject(error);
      try {
        writer.flush();
        resolve();
      } catch (problem) {
        reject(problem);
      }
    }

    const check = setInterval(() => {
      if (stopped() || Date.now() >= end || Date.now()-lastUpdate > 15000) finish();
    },1000);
    socket.addEventListener('open',() => {
      const marks = symbols.map(symbol => 'MARK:'+symbol);
      socket.send(JSON.stringify({type:'subscribe',payload:{channels:[
        {name:'mark_price',symbols:marks}, {name:'candlestick_1m',symbols:marks}, {name:'ob_l2',symbols},
      ]}}));
    });
    socket.addEventListener('message',event => {
      if (finished || stopped()) return;
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        console.error('Public protective quote stream sent an unreadable frame');
        finish();
        return;
      }
      if (message?.type === 'error') {
        console.error('Public protective quote subscription error');
        finish();
        return;
      }
      const row = marketRow(message,Date.now(),start,end,symbols);
      if (!row) return;
      try {
        writer.add(row);
        counts[symbols[row[1]]][row[0]]++;
        lastUpdate = row[3];
      } catch (error) {
        finish(error);
      }
    });
    socket.addEventListener('close',() => finish());
    socket.addEventListener('error',() => finish());
  });
}

async function main([run, identityJson, mode, ...symbols]) {
  const identity = JSON.parse(identityJson);
  const smoke = mode === 'smoke';
  if (identity.environment !== 'india_testnet' || !symbols.length ||
      (mode !== 'record' && !smoke)) throw new Error('Expected public Delta India testnet inputs');
  const start = smoke ? Date.now() : Date.parse(identity.start);
  const end = smoke ? start+45000 : Date.parse(identity.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) throw new Error('Invalid protective quote window');
  const stopFile = join(run,'STOP_CANDIDATE_PROTECTION');
  const counts = Object.fromEntries(symbols.map(symbol => [symbol,Object.fromEntries(kinds.map(kind => [kind,0]))]));
  const complete = () => symbols.every(symbol => kinds.every(kind => counts[symbol][kind] > 0));
  const stopped = () => smoke ? complete() : existsSync(stopFile);
  const makeWriter = streamId => smoke ? { add() {},flush() {} } : archiveStream(run,identity,symbols,streamId);
  console.log(JSON.stringify({mode,source:endpoint,start:new Date(start),end:new Date(end)}));
  while (!stopped() && Date.now() < end) {
    const remaining = start-Date.now();
    if (remaining > 0) await delay(Math.min(5000,remaining));
    else {
      await collect({start,end,symbols,stopped,makeWriter,counts});
      if (!stopped() && Date.now() < end) await delay(5000);
    }
  }
  console.log(JSON.stringify({counts}));
  if (smoke && !complete()) process.exitCode = 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
