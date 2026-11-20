import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";

const path = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(path(name)));
const digest = input => createHash("sha256").update(input).digest("hex");
assert.deepEqual(read("./isolation-probe.json"), { privateDenied: true, networkDenied: true });
const evidence = [];

for (const [id, config] of Object.entries(read("./pnl-table-feeds.json"))) {
  const source = fs.readFileSync(path(`./round26-source-${id}.pine`));
  const variant = fs.readFileSync(path(`./pnl-table-variant-${id}.pine`));
  const raw = source.toString("utf8");
  const archiveMetadata = raw.match(/^\/\*backtest[^]*?\*\/\r?\n/)[0];
  let archivedError = null;
  try {
    compile(raw.slice(archiveMetadata.length));
  } catch (error) {
    archivedError = error.message;
  }
  const metadataLines = archiveMetadata.split("\n").length - 1;
  const plan = compile(variant.toString("utf8"));
  assert(plan.metadata.isStrategy);
  assert.deepEqual(plan.metadata.securityDependencies, []);
  assert.deepEqual(plan.diagnostics, []);
  const cases = [];
  for (const [window, markets] of Object.entries(config.windows)) {
    for (const [market, candles] of Object.entries(markets)) {
      const points = candles.map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));
      const results = [];
      for (const backend of ["js", "interp"]) {
        const engine = new Engine(plan, new ArrayFeed(points), { backend, strategy: config.model });
        await engine.run({symbol: `BINANCE:${market}.P`, timeframe: config.frame, mintick: market === "BTCUSDT" ? 0.1 : 0.01});
        const plots = [...engine.outputs.plots.values()];
        results.push({
          witnesses: config.witnesses.map(title => plots.find(plot => plot.title === title).data),
          closed: engine.strategy.closedTrades,
          unsettled: engine.ctx.strategyBroker.openTradeCount
        });
      }
      assert.deepEqual(results[0], results[1]);
      cases.push({market, window, ...results[0]});
    }
  }
  evidence.push({id: Number(id), sourceHash: digest(source), variantHash: digest(variant), archivedError, metadataLines, cases});
}
fs.writeFileSync(path("./pnl-table-receipt.json"), JSON.stringify(evidence) + "\n");
