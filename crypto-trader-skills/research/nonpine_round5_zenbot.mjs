import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(work, "zenbot");
const main = "extensions/strategies/multi/strategy.js";
const allowed = new Set([
  ...["multi", "pivot", "macd", "ehlers_ft", "momentum"].map(
    name => `extensions/strategies/${name}/strategy.js`
  ),
  ...["ema", "rsi", "momentum", "phenotype", "helpers"].map(name => `lib/${name}.js`),
]);
const denied = /\b(?:process|globalThis|__proto__|constructor|Function|eval|child_process|fetch|WebSocket)\b/;
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const clean = code => code.replace(/\/\*[^]*?\*\/|\/\/[^\n]*/g, "");
const hashes = {};
const source = new Map();
for (const relative of allowed) {
  const bytes = fs.readFileSync(path.join(root, relative));
  source.set(relative, bytes.toString("utf8"));
  hashes[relative] = digest(bytes);
}
if (hashes[main] !== "07ec36f74585bd29a630bbed2d628fe90d78ceed36335066449e1d1f7cae9ae9") {
  throw Error("Zenbot multi source does not match the pinned archive");
}
// Host-generated arrays and VM arrays have different constructors.
source.set(main, source.get(main).replace("s.lookback.constructor === Array", "Array.isArray(s.lookback)"));

function loadStrategy() {
  const cache = new Map();
  const context = vm.createContext(Object.create(null), {
    codeGeneration: { strings: false, wasm: false },
  });
  function load(relative) {
    if (cache.has(relative)) return cache.get(relative).exports;
    const code = source.get(relative);
    if (!code || denied.test(clean(code))) throw Error(`Unverified module ${relative}`);
    const module = { exports: {} };
    cache.set(relative, module);
    const wrapper = new vm.Script("(function(module,exports,require){\n" + code + "\n})", { filename: relative });
    wrapper.runInContext(context, { timeout: 3000 })(module, module.exports, name => {
      if (name === "zero-fill" || name === "numbro") {
        // The offline adapter never calls the source's terminal display callbacks.
        return () => { throw Error("Unexpected access to a display-only module"); };
      }
      if (!name.startsWith(".")) throw Error(`Unverified module ${name}`);
      return load(path.posix.join(path.posix.dirname(relative), name + ".js"));
    });
    return module.exports;
  }
  return load(main);
}

function replay(bars) {
  const strategy = loadStrategy();
  const options = {};
  strategy.getOptions.call({ option(key, description, type, value) { options[key] = value; } });
  const state = { options: { ...options, period: "15m", period_length: "15m" }, lookback: [] };
  const trades = [];
  let position = null;
  let pending = null;
  for (const bar of bars) {
    if (bar.volume <= 0) throw Error("Expected a closed liquid bar");
    if (pending === "buy" && position === null) position = bar.open;
    else if (pending === "sell" && position !== null) {
      trades.push([bar.openTime, position, bar.open]);
      position = null;
    }
    state.period = { ...bar, time: bar.openTime, close_time: bar.closeTime, size: 1,
                     period_id: String(bar.openTime) };
    state.in_preroll = state.lookback.length < options.min_periods;
    state.signal = null;
    strategy.calculate(state);
    let complete = false;
    strategy.onPeriod(state, () => { complete = true; });
    if (!complete || ![null, "buy", "sell"].includes(state.signal)) throw Error("Unexpected signal");
    pending = state.in_preroll ? null : state.signal;
    state.lookback.unshift(state.period);
    if (state.lookback.length > 1000) state.lookback.pop();
  }
  return { trades, unsettled: Number(position !== null) };
}

const candleBytes = fs.readFileSync(path.join(work, "candles.json"));
const results = [];
for (const [period, markets] of Object.entries(JSON.parse(candleBytes))) {
  for (const [symbol, segments] of Object.entries(markets)) {
    if (segments.length !== 1) throw Error("Expected a continuous asset window");
    results.push({ period, symbol, ...replay(segments[0]) });
  }
}
fs.writeFileSync(path.join(work, "zenbot-multi-round5-raw.json"), JSON.stringify({
  id: 5888,
  source_sha256: hashes,
  candle_sha256: digest(candleBytes),
  results,
}));
