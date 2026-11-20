import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";

const path = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(path(name)));
const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");
assert.deepEqual(read("./isolation-probe.json"), { privateDenied: true, networkDenied: true });

const code = fs.readFileSync(path("./variant-1884.pine"));
const plan = compile(code.toString("utf8"));
assert(plan.metadata.isStrategy);
assert.deepEqual(plan.metadata.securityDependencies, []);
assert.deepEqual(plan.diagnostics, []);
assert.equal(plan.metadata.strategy.marginLong, 4);
assert.equal(plan.metadata.strategy.marginShort, 2);

const settings = {
  initialCapital: 10000,
  qtyType: "cash",
  qtyValue: 1000,
  commissionType: "percent",
  commissionValue: 0.059,
  marginLong: 4,
  marginShort: 2,
};

const cases = [];
const witnessTitles = ["Fast proof", "Slow proof", "K proof", "D proof", "Long proof", "Short proof"];
for (const [period, markets] of Object.entries(read("./feeds.json"))) {
  for (const [market, rows] of Object.entries(markets)) {
    const bars = rows.map(([time, open, high, low, close, volume]) => ({
      time, open, high, low, close, volume,
    }));
    const runs = [];
    for (const backend of ["js", "interp"]) {
      const engine = new Engine(plan, new ArrayFeed(bars), { backend, strategy: settings });
      await engine.run({
        symbol: `BINANCE:${market}.P`, timeframe: "D", mintick: market === "BTCUSDT" ? 0.1 : 0.01,
      });
      const outputs = [...engine.outputs.plots.values()];
      runs.push({
        witnesses: witnessTitles.map(title => outputs.find(plot => plot.title === title).data),
        closed: engine.strategy.closedTrades,
        unsettled: engine.ctx.strategyBroker.openTradeCount,
      });
    }
    assert.deepEqual(runs[0], runs[1]);
    cases.push({ period, market, ...runs[0] });
  }
}

const receipt = {
  source_hash: sha256(fs.readFileSync(path("./source-1884.pine"))),
  variant_hash: sha256(code),
  settings,
  cases,
};
fs.writeFileSync(path("./receipt.json"), JSON.stringify(receipt) + "\n");
