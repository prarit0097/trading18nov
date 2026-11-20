import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";

const load = name => fs.readFileSync(new URL(name, import.meta.url));
const read = name => JSON.parse(load(name));
const write = (name, value) => fs.writeFileSync(
  new URL(name, import.meta.url), JSON.stringify(value) + "\n",
);
const sha256 = data => createHash("sha256").update(data).digest("hex");
const action = process.argv[2];
const isolation = read("./isolation-probe.json");
assert.deepEqual(isolation, { privateDenied: true, networkDenied: true });

function compileArchive(item) {
  const bytes = load(`./source-${item.id}.pine`);
  assert.equal(sha256(bytes), item.source_sha256);
  return compile(bytes.toString("utf8"));
}

function probe() {
  const out = [];
  for (const item of read("./compile-input.json")) {
    try {
      const plan = compileArchive(item);
      out.push({
        id: item.id,
        isStrategy: plan.metadata.isStrategy,
        strategy: plan.metadata.strategy,
        diagnostics: plan.diagnostics,
        security: plan.metadata.securityDependencies,
        inputs: plan.metadata.inputs,
      });
    } catch (err) {
      out.push({ id: item.id, error: String(err) });
    }
  }
  write("./compile-results.json", out);
}

const commissions = {
  commissionType: "percent",
  commissionValue: 0.059,
};
const chartOptions = {
  BTCUSDT: { symbol: "BINANCE:BTCUSDT.P", timeframe: "15", mintick: 0.1 },
  ETHUSDT: { symbol: "BINANCE:ETHUSDT.P", timeframe: "15", mintick: 0.01 },
};

function model(settings, version) {
  return {
    initialCapital: settings.initialCapital ?? 10000,
    qtyType: settings.qtyType ?? "cash",
    qtyValue: settings.qtyValue ?? (settings.qtyType ? 1 : 1000),
    marginLong: settings.marginLong ?? (version === "6" ? 100 : 0),
    marginShort: settings.marginShort ?? (version === "6" ? 100 : 0),
    ...commissions,
  };
}

async function run(plan, bars, options, settings, backend) {
  const engine = new Engine(plan, new ArrayFeed(bars), { backend, strategy: settings });
  await engine.run(options);
  return {
    closed: engine.strategy.closedTrades,
    unsettled: engine.ctx.strategyBroker.openTradeCount,
  };
}

async function fixture() {
  const source = `//@version=5
strategy("R7 commission and timing", initial_capital=40000)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    strategy.close("L")
if bar_index == 2
    strategy.entry("S", strategy.short, qty=1)
if bar_index == 3
    strategy.close("S")
if bar_index == 4
    strategy.entry("Default", strategy.long)
if bar_index == 5
    strategy.close("Default")
`;
  const plan = compile(source);
  const interval = 900_000;
  const start = 1767225600000;
  const bars = [100, 101, 110, 103, 97, 100, 102].map((open, i) => ({
    time: start + i * interval,
    open, high: open + 1, low: open - 1, close: open, volume: 1,
  }));
  const reports = [];
  for (const backend of ["js", "interp"]) {
    const result = await run(plan, bars, chartOptions.BTCUSDT, model({}, "5"), backend);
    assert.equal(result.closed.length, 3);
    assert.equal(result.unsettled, 0);
    const [long, short, defaults] = result.closed;
    assert.deepEqual(
      [long.dir, long.qty, long.entryPrice, long.exitPrice, long.entryTime, long.exitTime],
      [1, 2, 101, 110, bars[1].time, bars[2].time],
    );
    assert.deepEqual(
      [short.dir, short.qty, short.entryPrice, short.exitPrice, short.entryTime, short.exitTime],
      [-1, 1, 103, 97, bars[3].time, bars[4].time],
    );
    assert(Math.abs(long.commission - 211 * 2 * 0.00059) < 1e-10);
    assert(Math.abs(short.commission - 200 * 0.00059) < 1e-10);
    assert(Math.abs(long.profit - (18 - long.commission)) < 1e-10);
    assert(Math.abs(short.profit - (6 - short.commission)) < 1e-10);
    assert.deepEqual([defaults.dir, defaults.qty, defaults.entryPrice, defaults.exitPrice],
      [1, 10, 100, 102]);
    reports.push(result);
  }
  assert.deepEqual(reports[0], reports[1]);
  write("./fixture.json", {
    verified: true, feesPerSide: 0.00059, bothBackendsEqual: true,
    testScriptSha256: sha256(source), sample: reports[0].closed,
  });
}

async function replay() {
  assert.equal(read("./fixture.json").sample.length, 3);
  const charts = read("./chart-bars.json");
  const out = [];
  for (const item of read("./replay-input.json")) {
    try {
      const plan = compileArchive(item);
      assert(plan.metadata.isStrategy);
      assert.deepEqual(plan.diagnostics, []);
      assert.deepEqual(plan.metadata.securityDependencies, []);
      assert.equal(plan.metadata.strategy.useBarMagnifier ?? false, false);
      const settings = model(plan.metadata.strategy, item.header_version[0]);
      const cases = [];
      for (const [period, markets] of Object.entries(charts)) {
        for (const [market, [candles]] of Object.entries(markets)) {
          const bars = candles.map(({ openTime: time, open, high, low, close, volume }) => ({
            time, open, high, low, close, volume,
          }));
          const javascript = await run(plan, bars, chartOptions[market], settings, "js");
          const interpreter = await run(plan, bars, chartOptions[market], settings, "interp");
          assert.deepEqual(javascript, interpreter, `${period} ${market}: backend disagreement`);
          cases.push({ period, market, ...javascript });
        }
      }
      out.push({ id: item.id, source_sha256: item.source_sha256, settings, cases });
    } catch (err) {
      out.push({ id: item.id, error: String(err).split("\n")[0] });
    }
    write("./replay-receipts.json", out);
  }
}

if (action === "probe") probe();
else if (action === "fixture") await fixture();
else if (action === "replay") await replay();
else throw Error("Expected probe, fixture or replay");
