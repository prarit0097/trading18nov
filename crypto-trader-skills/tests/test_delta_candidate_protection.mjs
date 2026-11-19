import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmdirSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { gunzipSync } from 'node:zlib';
import { marketRow, writeChunk } from '../crypto_skills/delta_candidate_protection.mjs';

const start = 1795120000000;
const end = start + 300000;
const received = start + 300;
const timestamp = start * 1000 + 250000;
const symbols = ['BTCUSD', 'ETHUSD'];

test('paired tape retains precise reception, source times and displayed depth', () => {
  const depth = [['10.01','2'],['10.00','3'],['9.90','1'],['9.80','2'],['9.70','3'],['9.60','5']];
  const row = marketRow({type:'ob_l2',sy:'BTCUSD',ts:timestamp,lts:timestamp-100000,
    b:depth,a:[['10.02','4'],['10.03','2']]}, received, start, end, symbols);
  assert.deepEqual(row,['book',0,timestamp,received,timestamp-100000,depth.slice(0,5),['10.02','4']]);
  assert.deepEqual(marketRow({type:'mark_price',sy:'MARK:ETHUSD',ts:timestamp,p:'10.015'},
    received,start,end,symbols),['mark',1,timestamp,received,'10.015']);
  const minute=Math.floor(timestamp/60000000)*60000000;
  const candle={type:'candlestick_1m',sy:'MARK:ETHUSD',ts:timestamp,cst:minute,
    o:'10',h:'10.2',l:'9.99',c:'10.1'};
  assert.deepEqual(marketRow(candle,received,start,end,symbols),
    ['candle',1,timestamp,received,minute,'10','10.2','9.99','10.1']);
  assert.equal(marketRow({...candle,cst:minute+1},received,start,end,symbols),null);
});

test('foreign, crossed, stale or out-of-window feed events stay absent', () => {
  const valid={type:'mark_price',sy:'MARK:BTCUSD',ts:timestamp,p:'10.01'};
  for (const wrong of [{...valid,sy:'MARK:SOLUSD'},{...valid,p:'0'},{...valid,ts:(start-1)*1000},
    {type:'ob_l2',sy:'BTCUSD',ts:timestamp,lts:timestamp,b:[['10','2']],a:[['9','2']]}]) {
    assert.equal(marketRow(wrong,received,start,end,symbols),null);
  }
  assert.equal(marketRow(valid,received+4000,start,end,symbols),null);
  assert.equal(marketRow(valid,end,start,end,symbols),null);
});

test('archived chunks are independently readable and retain their registration', () => {
  const directory=mkdtempSync(join(tmpdir(),'delta-protection-test-'));
  try {
    const identity={version:'fixture',evidence_sha256:'digest'};
    const row=['mark',0,timestamp,received,'10.015'];
    const file=writeChunk(directory,{identity,symbols,stream_id:'test-stream',first_receipt_ms:received},[row]);
    const lines=gunzipSync(readFileSync(file)).toString('utf8').trim().split('\n').map(JSON.parse);
    assert.equal(lines[0].identity.evidence_sha256,'digest');
    assert.deepEqual(lines[1],row);
    assert.equal(readdirSync(directory).length,1);
  } finally {
    for (const file of readdirSync(directory)) unlinkSync(join(directory,file));
    rmdirSync(directory);
  }
});
