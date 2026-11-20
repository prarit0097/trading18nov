import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";

const read = (name) => fs.readFileSync(new URL(name, import.meta.url));
const enginePath = "./package/dist/index.js";
const digest = "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea";
assert.equal(createHash("sha256").update(read(enginePath)).digest("hex"), digest);
assert.equal(createHash("sha512").update(read("piner-0.13.0.tgz")).digest("base64"),
  "wyZp7irvRiBBoSkLINDqufqRsc6rZH7uoIwk1dZHlKIkLBz+fpeBi7mbgumRxiyBNZf2dN6YmiE6swRhWE9wNw==");
const { compile, Engine, ArrayFeed } = await import(enginePath);

const native = JSON.parse(read("5211-reservation.json"));
const results = {};
for (const { case: name, source } of native.cases) {
  const program = compile(source);
  const outputs = {};
  if (program.diagnostics.length === 0) {
    for (const backend of ["js", "interp"]) {
      const engine = new Engine(program, new ArrayFeed(native.bars), { backend,
        strategy: { minQty: 1, marginLong: 0, marginShort: 0 } });
      await engine.run({ symbol: "BINANCE:BTCUSDT", timeframe: "D", mintick: 1 });
      outputs[backend] = engine.strategy;
    }
    assert.deepEqual(outputs.js, outputs.interp);
  }
  results[name] = { diagnostics: program.diagnostics, broker: outputs.js ?? null };
}
fs.writeFileSync(new URL("5211-piner-fixtures.json", import.meta.url), JSON.stringify({ engine: digest, results }));
