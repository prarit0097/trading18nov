import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";

const read = (name) => fs.readFileSync(new URL(name, import.meta.url));
const parse = (name) => JSON.parse(read(name));
const sha = (buffer) => createHash("sha256").update(buffer).digest("hex");
const enginePath = "./package/dist/index.js";
const digest = "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea";
assert.equal(sha(read(enginePath)), digest);
assert.equal(createHash("sha512").update(read("piner-0.13.0.tgz")).digest("base64"),
  "wyZp7irvRiBBoSkLINDqufqRsc6rZH7uoIwk1dZHlKIkLBz+fpeBi7mbgumRxiyBNZf2dN6YmiE6swRhWE9wNw==");
const { compile, Engine, ArrayFeed } = await import(enginePath);

async function run(script, bars, market) {
  const program = compile(script);
  assert.deepEqual(program.diagnostics, []);
  const series = [];
  for (const backend of ["js", "interp"]) {
    const engine = new Engine(program, new ArrayFeed(bars), {
      backend,
      strategy: { minQty: .001, marginLong: 0, marginShort: 0 },
    });
    await engine.run({ symbol: `BINANCE:${market}`, timeframe: "D", mintick: market === "BTCUSDT" ? .1 : .01 });
    series.push(engine.strategy);
  }
  assert.deepStrictEqual(...series);
  return series[0];
}

const authored = read("source-2994.md");
assert.equal(sha(authored), "f9ccc275870a1bd0cb3dab7160fe0a46fa4c719c07aeb139798aeb28baf7c265");
const lines = authored.toString("utf8").split("\n");
const header = lines.find((line) => line.startsWith("strategy(title='VMC'"));
assert.equal(header, "strategy(title='VMC', shorttitle='VMC', overlay=true, precision=3, commission_value=0.025, default_qty_type=strategy.cash, default_qty_value=10000, initial_capital=10000)");
const body = lines.filter((line) => line.startsWith("strategy.entry(") || line.startsWith("strategy.close("));
assert.equal(body.length, 4);

const synthetic = [[100, 100], [190.3, 191.1], [277.6, 270.8], [208.1, 210.3]].map(([open, close], i) => ({
  time: 1702944000000 + i * 86400000, open, high: Math.max(open, close), low: Math.min(open, close), close, volume: 1,
}));
const fixture = await run(`//@version=5\n${header}
if bar_index == 0
    strategy.entry("long", strategy.long)
if bar_index == 1
    strategy.close("long")
    strategy.entry("short", strategy.short)
if bar_index == 2
    strategy.close("short")`, synthetic, "BTCUSDT");

const data = parse("2994-replay.json");
const bindings = {
  "Observed long": "long_entry",
  "Observed short": "short_entry",
  "Observed short-side close": "long_exit_entry",
  "Observed long-side close": "short_exit_entry",
};
const sample = [];
for (const raw of data) {
  const path = raw.file;
  const payload = parse(path);
  const { market } = payload;
  const chart = payload.day.map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));
  const stmts = [];
  for (const [title, name] of Object.entries(bindings)) {
    const r = raw.observed.plots.find((plot) => plot.title === title);
    assert.equal(r.values.length, chart.length);
    assert(r.values.every((value) => value === 0 || value === 1));
    const plus = r.values.flatMap((value, index) => value === 1 ? [index] : []);
    assert(plus.length > 0);
    const ca = plus.map((index) => `    ${index} => true`).join("\n");
    stmts.push(`${name} = switch bar_index\n${ca}\n    => false`);
  }
  const replay = `//@version=5\n${header}\n${stmts.join("\n")}\ncloseStatus = strategy.openprofit > 0 ? 'win' : 'lose'\n${body.join("\n")}\n`;
  const result = await run(replay, chart, market);
  sample.push({ market, sourceSha256: sha(Buffer.from(replay)), dataSha256: sha(read(path)), result });
}

fs.writeFileSync(new URL("2994-piner.json", import.meta.url), JSON.stringify({ engine: digest, fixture, sample }));
