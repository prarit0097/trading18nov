import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const model = "extensions/strategies/neural/strategy.js";
const hashes = {
  "convnet.js": "f4d8714f3a7fb98dea574f2c7eb99c5b0e3dbd0d246a89432fa4f52f7f4b5fc2",
  [model]: "4c927ea698437f012c010140be589fecc6e93845de6098febe59e3e726c2b546",
  "lib/ema.js": "bc4aa9e936e57ae629267d49844386cb8da979e8ba564233145ed7cbe60e2416",
  "lib/phenotype.js": "552400fee8eeb974e84110b136fe0089183bf8f76f54948f89feea36b30ab1f2",
};
const digest = buffer => createHash("sha256").update(buffer).digest("hex");
const sources = Object.fromEntries(Object.entries(hashes).map(([file, expected]) => {
  const bytes = fs.readFileSync(path.join(root, file));
  if (digest(bytes) !== expected) throw Error(`Unexpected bytes in ${file}`);
  return [file, bytes.toString("utf8")];
}));
const seed = 5889;
const [limitArg = "48", marketFilter = "", periodFilter = "", runtime = "context"] = process.argv.slice(2);
const testBars = Number(limitArg);
if (![8, 16, 48].includes(testBars) || !["", "BTC", "ETH"].includes(marketFilter)
    || !["", "2026-10-01", "2026-11-01"].includes(periodFilter)
    || !["context", "direct"].includes(runtime)) {
  throw Error("Invalid fixed replay scope");
}

function loadWorker() {
  const context = vm.createContext(Object.create(null), {
    codeGeneration: { strings: false, wasm: false },
  });
  vm.runInContext(`
    let replaySeed = ${seed};
    Math.random = () => {
      replaySeed = (Math.imul(1664525, replaySeed) + 1013904223) >>> 0;
      return replaySeed / 4294967296;
    };
    globalThis.global = globalThis;
  `, context);

  const allowed = new Map([
    ["convnetjs", "convnet.js"],
    ["../../../lib/ema", "lib/ema.js"],
    ["../../../lib/phenotype", "lib/phenotype.js"],
  ]);
  const cache = new Map();
  const workerGlobal = Object.create(null);
  let workerSeed = seed;
  const workerMath = Object.create(Math);
  workerMath.random = () => {
    workerSeed = (Math.imul(1664525, workerSeed) + 1013904223) >>> 0;
    return workerSeed / 4294967296;
  };
  function load(file) {
    if (cache.has(file)) return cache.get(file).exports;
    if (!Object.hasOwn(sources, file)) throw Error("Module is outside the pinned replay");
    const module = { exports: {} };
    cache.set(file, module);
    const require = name => {
      if (name === "cluster") return Object.freeze({ isMaster: false, isWorker: true });
      if (name === "numbro" || name === "zero-fill") {
        return () => { throw Error("The historical worker must not use terminal reporting"); };
      }
      if (!allowed.has(name)) throw Error(`Dependency ${name} is missing from the source pin`);
      return load(allowed.get(name));
    };
    if (runtime === "direct") {
      // The pinned worker is still run under AppContainer and Node file
      // permissions. Compile its callbacks in the same realm as the bar data.
      const fn = vm.compileFunction(sources[file], ["module", "require", "Math", "global", "process"],
        { filename: file });
      fn(module, require, workerMath, workerGlobal, undefined);
    } else {
      const fn = new vm.Script("(function(module, require){\n" + sources[file] + "\n})",
        { filename: file }).runInContext(context, { timeout: 3000 });
      fn(module, require);
    }
    return module.exports;
  }
  return load(model);
}

function replay(bars, reportProgress) {
  const worker = loadWorker();
  const options = {};
  worker.getOptions.call({ option(key, description, type, value) { options[key] = value; } });
  if (options.period_length !== "30m" || options.min_periods !== 2000 || options.learns !== 10) {
    throw Error("Unexpected archived defaults");
  }
  const state = { options, lookback: [] };
  const trades = [];
  const signals = [];
  let position = null;
  let pending = null;
  for (const bar of bars) {
    if (!Number.isFinite(bar.close) || bar.close <= 0 || bar.volume < 0) throw Error("Bad closed bar");
    if (pending === "buy" && !position) position = { at: bar.openTime, price: bar.open };
    if (pending === "sell" && position) {
      trades.push([position.at, bar.openTime, position.price, bar.open]);
      position = null;
    }
    state.period = bar;
    state.in_preroll = state.lookback.length <= options.min_periods;
    state.signal = null;
    let callback = false;
    worker.calculate(state);
    worker.onPeriod(state, () => { callback = true; });
    if (!callback) throw Error("Worker callback did not complete");
    if (!state.in_preroll) {
      if (!Number.isFinite(state.prediction)) throw Error("Non-finite network prediction");
      if (!["buy", "sell"].includes(state.signal)) throw Error("Unexpected strategy advice");
      signals.push([bar.closeTime, state.signal, state.prediction]);
      reportProgress(signals.length);
    }
    pending = state.in_preroll ? null : state.signal;
    state.lookback.unshift(state.period);
    if (state.lookback.length > 2001) state.lookback.pop();
  }
  if (signals.length !== testBars) throw Error("Incomplete 30-minute test sample");
  return { trades, signals, unsettled: Number(position !== null) };
}

const raw = fs.readFileSync(path.join(root, "candles.json"));
const results = [];
const tag = [testBars, marketFilter, periodFilter, runtime === "direct" ? runtime : ""].filter(Boolean).join("-");
for (const [period, markets] of Object.entries(JSON.parse(raw))) {
  if (periodFilter && periodFilter !== period) continue;
  for (const [market, bars] of Object.entries(markets)) {
    if (marketFilter && marketFilter !== market) continue;
    const measured = replay(bars.slice(0, 2001 + testBars), count => {
      const file = path.join(root, `neural-progress-${tag}.json`);
      fs.writeFileSync(file, JSON.stringify({ period, market, count, testBars }));
    });
    results.push({ period, market, ...measured });
  }
}
fs.writeFileSync(path.join(root, `neural-results-${tag}.json`), JSON.stringify({
  source_hashes: hashes,
  candle_sha256: digest(raw),
  seed,
  runtime,
  source_spec: "ConvNetJS 0.3.0 and Zenbot 52872fb4b5f9",
  results,
}));
