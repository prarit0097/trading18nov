import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const work = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(work, "package.json"));
const lodash = dependency("lodash");
const toml = dependency("@iarna/toml");
const ta = dependency("talib-web");
const wasm = await ta.init(path.join(work, "node_modules", "talib-web", "lib", "talib.wasm"));
const api = JSON.parse(fs.readFileSync(dependency.resolve("talib-web"), "utf8").match(/^const API = (\{[^\n]+\});$/m)[1]);
const tulip = dependency(path.join(work, "tulind.node"));
const inputs = JSON.parse(fs.readFileSync(path.join(work, "legacy-candidates.json"), "utf8"));
const windows = JSON.parse(fs.readFileSync(path.join(work, "candles.json"), "utf8"));
const noLog = Object.freeze({ debug() {}, info() {}, warn() {}, error() {} });
const denied = /\b(?:process|globalThis|__proto__|constructor|Function|eval|child_process|fetch|WebSocket)\b/;
const purePackages = new Set(["zero-fill", "numbro", "bollinger-bands", "stats-lite", "mathjs", "trend", "keltnerchannel"]);
const functions = new Set(["EMA", "MACD", "MACDEXT", "PPO", "BBANDS", "STOCHRSI", "STOCH", "TRIX", "ULTOSC"]);
const tulind = { indicators: {} };
for (const name of ["bbands", "hma", "stoch", "adx", "macd", "rsi"]) {
  const indicator = tulip.indicators[name];
  tulind.indicators[name] = { ...indicator, indicator: (input, options, cb) => {
    if (typeof cb === "function") return tulip.callbyindex(indicator.index, input, options, cb);
    return new Promise((resolve, reject) => tulip.callbyindex(indicator.index, input, options,
      (error, result) => error ? reject(error) : resolve(result)));
  }};
}

const talib = { execute(options, callback) {
  const name = options.name.toUpperCase();
  if (!functions.has(name)) throw Error("Unsupported archived TA-Lib callback: " + name);
  const params = {};
  for (const [key, value] of Object.entries(options)) {
    if (key.startsWith("optIn")) {
      const input = key.slice(5);
      params[input === "MAType" ? input : input[0].toLowerCase() + input.slice(1)] = value;
    } else if (key === "inReal") params.inReal = value;
    else if (["high", "low", "open", "close", "volume", "inHigh", "inLow", "inOpen", "inClose", "inVolume"].includes(key)) {
      const input = key.startsWith("in") ? key.slice(2).toLowerCase() : key;
      params[input] = value;
    }
  }
  const spec = api[name];
  const managed = [];
  const alloc = size => {
    const p = wasm._malloc(size);
    if (!p) throw Error("TA-Lib WASM allocation failed");
    managed.push(p);
    return p;
  };
  try {
    const args = [options.startIdx, options.endIdx];
    for (const field of spec.inputs) {
      const data = params[field.name];
      if (!Array.isArray(data) || data.length <= options.endIdx) throw Error("Missing TA-Lib input " + field.name);
      const ptr = alloc(data.length * 8);
      wasm.HEAPF64.set(data, ptr / 8);
      args.push(ptr);
    }
    for (const field of spec.options) args.push(params[field.name] ?? field.defaultValue);
    const count = alloc(8);
    wasm.HEAP32.fill(0, count / 4, count / 4 + 2);
    args.push(count, count + 4);
    const outputs = spec.outputs.map(() => alloc((options.endIdx + 1) * 8));
    args.push(...outputs);
    const code = wasm.ccall("TA_" + name, "number", args.map(() => "number"), args);
    if (code !== 0) throw Error(`TA-Lib ${name} returned ${code}`);
    const length = wasm.HEAP32[count / 4 + 1];
    if (length < 0 || length > options.endIdx - options.startIdx + 1) throw Error("Invalid TA-Lib output length");
    const result = {};
    spec.outputs.forEach(({name: key}, i) => {
      const next = key === "output" ? "outReal" : "out" + key[0].toUpperCase() + key.slice(1);
      result[next] = Array.from(wasm.HEAPF64.subarray(outputs[i] / 8, outputs[i] / 8 + length));
    });
    const response = { result };
    if (callback) callback(null, response);
    return response;
  } finally {
    managed.forEach(p => wasm._free(p));
  }
}};
const emaFixture = talib.execute({ name: "EMA", startIdx: 0, endIdx: 7, inReal: [1,2,3,4,5,6,7,8], optInTimePeriod: 3 });
if (String(emaFixture.result.outReal) !== "2,3,4,5,6,7") throw Error("TA-Lib EMA fixture failed");

function createSourceLoader(root, family, config) {
  const cache = new Map();
  const context = vm.createContext(Object.create(null), {
    codeGeneration: { strings: false, wasm: false }
  });

  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports;
    const relative = path.relative(root, filename).split(path.sep).join("/");
    if (!(family === "gekko" ? relative.startsWith("strategies/") : /^(extensions\/strategies\/|lib\/)/.test(relative)))
      throw Error("Dependency outside the pinned strategy sources");
    if (!fs.existsSync(filename)) throw Error("Pinned dependency unavailable");
    const code = fs.readFileSync(filename, "utf8");
    if (denied.test(code.replace(/\/\*[^]*?\*\/|\/\/[^\n]*/g, "")))
      throw Error("Module uses a host or unsupported runtime capability");
    const module = { exports: {} };
    cache.set(filename, module);
    const wrapper = new vm.Script("(function(module,exports,require){\n" + code + "\n})", { filename });
    wrapper.runInContext(context, { timeout: 300 })(module, module.exports, (id) => {
      if (id === "lodash") return lodash;
      if (id === "talib") return talib;
      if (id === "tulind") return tulind;
      if (family === "zenbot" && relative === "extensions/strategies/rsi/strategy.js" && id === "../../../lib/engine") return {};
      if (purePackages.has(id)) return dependency(id);
      if (/^\.\.?\/.*core\/log(?:\.js)?$/.test(id)) return noLog;
      if (/^\.\.?\/.*core\/util(?:\.js)?$/.test(id)) return { getConfig: () => config };
      if (id.startsWith(".")) {
        const target = path.resolve(path.dirname(filename), id + (path.extname(id) ? "" : ".js"));
        return load(target);
      }
      throw Error("Dependency " + id + " requires its original framework or indicator library");
    });
    return module.exports;
  }
  return load;
}

function configForGekko(root) {
  const config = {};
  const configs = path.join(root, "config", "strategies");
  for (const file of fs.readdirSync(configs)) {
    if (file.endsWith(".toml")) config[file.slice(0, -5)] = toml.parse(fs.readFileSync(path.join(configs, file), "utf8"));
  }
  config.tradingAdvisor = toml.parse(fs.readFileSync(path.join(root, "config", "plugins", "tradingAdvisor.toml"), "utf8"));
  return config;
}

function gekkoAdvice(relative, root, config) {
  const settings = config[path.basename(relative, ".js")];
  if (!settings) throw Error("Pinned Gekko strategy defaults unavailable");
  const load = createSourceLoader(root, "gekko", config);
  let decision;
  const host = {
    ...load(path.join(root, relative)),
    indicators: {}, tradingAdvisor: { ...config.tradingAdvisor, candleSize: 15 }, settings,
    addIndicator(name, type, parameters) {
      if (!/^\w+$/.test(type)) throw Error("Unsupported indicator name");
      const Indicator = load(path.join(root, "strategies", "indicators", type + ".js"));
      this.indicators[name] = new Indicator(parameters);
      return this.indicators[name];
    },
    advice(direction) {
      if (direction && !["long", "short"].includes(direction)) throw Error("Order advice uses an unsupported trigger");
      if (direction) decision = direction === "long" ? "buy" : "sell";
    },
    talibIndicators: {}, tulipIndicators: {},
    addTalibIndicator(name, type, parameters) {
      if (type !== "macd") throw Error("Unsupported Gekko TA-Lib indicator: " + type);
      this.talibIndicators[name] = { parameters, result: {} };
    },
    addTulipIndicator(name, type, parameters) {
      if (!Object.hasOwn(tulind.indicators, type)) throw Error("Unsupported Gekko Tulip indicator: " + type);
      this.tulipIndicators[name] = { type, parameters, result: {} };
    }
  };
  if (typeof host.init !== "function" || typeof host.check !== "function") throw Error("Strategy advice callbacks unavailable");
  host.init();
  let age = 0;
  const series = { high: [], low: [], close: [] };
  return async (bar) => {
    decision = undefined;
    const candle = { ...bar, vwp: (bar.high + bar.low + bar.close) / 3 };
    for (const field of Object.keys(series)) {
      series[field].push(candle[field]);
      if (series[field].length > 1000) series[field].shift();
    }
    for (const indicator of Object.values(host.talibIndicators)) {
      const out = talib.execute({ name: "MACD", startIdx: 0, endIdx: series.close.length-1,
        inReal: series.close, ...indicator.parameters }).result;
      indicator.result = Object.fromEntries(Object.entries(out).map(([key, vals]) => [key, vals.at(-1)]));
    }
    for (const indicator of Object.values(host.tulipIndicators)) {
      const {type, parameters} = indicator;
      const lib = tulind.indicators[type];
      const params = type === "macd" ? [parameters.optInFastPeriod, parameters.optInSlowPeriod, parameters.optInSignalPeriod] : [parameters.optInTimePeriod];
      const price = lib.input_names.map(field => series[field === "real" ? "close" : field]);
      if (series.close.length < Math.max(3, ...params)) continue;
      const result = await lib.indicator(price, params.map(Math.trunc));
      indicator.result = Object.fromEntries(lib.output_names.map((key, i) => [key, result[i].at(-1)]));
      if (result.length === 1) indicator.result.result = result[0].at(-1);
    }
    for (const indicator of Object.values(host.indicators)) {
      if (indicator.input === "price") indicator.update(candle.close);
      else if (indicator.input === "candle") indicator.update(candle);
    }
    host.candle = candle;
    host.update?.(candle);
    if (++age >= (host.requiredHistory ?? config.tradingAdvisor.historySize)) host.check(candle);
    return decision;
  };
}

function zenbotAdvice(relative, root) {
  const load = createSourceLoader(root, "zenbot", {});
  const strategy = load(path.join(root, relative));
  if (typeof strategy.getOptions !== "function" || typeof strategy.onPeriod !== "function")
    throw Error("Strategy callbacks unavailable");
  const options = {};
  strategy.getOptions.call({ option(key, description, type, value) { options[key] = value; } });
  const state = { options: { ...options, period_length: "15m", period: "15m" }, lookback: [],
                  action: null, signal: null, balance: { asset: 0, currency: 10000 } };
  return async (bar, position, fills) => {
    state.period = { ...bar, time: bar.openTime, close_time: bar.closeTime, size: 1,
                     period_id: String(bar.openTime) };
    state.in_preroll = state.lookback.length < (options.min_periods ?? 25);
    state.in_preroll = Boolean(state.in_preroll);
    state.signal = null;
    const lastFill = fills.at(-1);
    state.action = lastFill ? lastFill.type === "buy" ? "bought" : "sold" : null;
    state.my_trades = fills;
    state.my_prev_trades = [];
    state.last_trade_worth = lastFill ? (lastFill.type === "buy" ? 1 : -1) * (bar.close - lastFill.price) / lastFill.price : 0;
    state.balance.asset = position ? 1000 / position : 0;
    state.asset_capital = state.balance.asset * bar.close;
    strategy.calculate?.(state);
    let setCallback;
    const barrier = new Promise(resolve => { setCallback = resolve; });
    const callback = error => setCallback(error);
    const result = strategy.onPeriod(state, callback);
    if (result?.then) await result;
    else if (strategy.onPeriod.length >= 2) {
      let timer;
      try {
        const error = await Promise.race([barrier, new Promise((_,reject) => {
          timer = setTimeout(() => reject(Error("Archived onPeriod callback did not complete")), 1200);
        })]);
        if (error) throw error;
      } finally { clearTimeout(timer); }
    }
    state.lookback.unshift(state.period);
    if (state.lookback.length > 1000) state.lookback.pop();
    if (state.in_preroll) return;
    if (state.signal === "sold") return; // The pinned engine has no order branch for this signal.
    if (state.signal && !["buy", "sell"].includes(state.signal)) throw Error("Unknown order signal");
    return state.signal;
  };
}

async function replay(item, root, relative, config) {
  const summaries = [];
  for (const [period, markets] of Object.entries(windows)) {
    for (const [symbol, segments] of Object.entries(markets)) {
      const trades = [];
      let unsettled = 0;
      for (const candles of segments) {
        const check = item.source === "gekko" ? gekkoAdvice(relative, root, config)
                                               : zenbotAdvice(relative, root);
        const fills = [];
        let active = null, next = null;
        for (const bar of candles) {
          if (bar.volume > 0) {
            if (next === "buy" && !active) {
              active = bar.open;
              fills.push({ type: "buy", price: bar.open, time: bar.openTime, size: 1000 / active });
            }
            else if (next === "sell" && active) {
              trades.push([bar.openTime, active, bar.open]);
              fills.push({ type: "sell", price: bar.open, time: bar.openTime, size: 1000 / active });
              active = null;
            }
            next = null;
          }
          const advice = await check(bar, active, fills);
          if (advice) next = advice;
        }
        unsettled += Number(active != null);
      }
      summaries.push({ period, symbol, trades, unsettled });
    }
  }
  return summaries;
}

const roots = { gekko: path.join(work, "gekko"), zenbot: path.join(work, "zenbot") };
const config = configForGekko(roots.gekko);
const write = row => fs.appendFileSync(path.join(work, "legacy-raw.jsonl"), JSON.stringify(row) + "\n");
fs.writeFileSync(path.join(work, "legacy-raw.jsonl"), "");
for (const item of inputs) {
  if (/(?:^DEBUG|^noop$|^custom$)/i.test(item.name)) {
    write({ id: item.id, reason: "Demonstration, no-op or control example" });
    continue;
  }
  const relative = item.source_url.split("/blob/")[1].split("/").slice(1).join("/");
  const root = roots[item.source];
  try {
    const results = await replay(item, root, relative, config);
    const hash = createHash("sha256").update(fs.readFileSync(path.join(root, relative))).digest("hex");
    write({ id: item.id, hash, results });
  } catch (error) {
    const reason = String(error.message).replace(/[\r\n].*/, "");
    write({ id: item.id, reason });
  }
}
