import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";

const work = path.resolve(process.argv[2]);
const dependency = createRequire(path.join(work, "package.json"));
const lodash = dependency("lodash");
const toml = dependency("@iarna/toml");
const inputs = JSON.parse(fs.readFileSync(path.join(work, "legacy-candidates.json"), "utf8"));
const windows = JSON.parse(fs.readFileSync(path.join(work, "candles.json"), "utf8"));
const noLog = Object.freeze({ debug() {}, info() {}, warn() {}, error() {} });
const denied = /\b(?:process|globalThis|__proto__|constructor|Function|eval|child_process|fetch|WebSocket)\b/;
const purePackages = new Set(["zero-fill", "numbro", "bollinger-bands", "stats-lite", "mathjs", "trend"]);

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
    addTalibIndicator() { throw Error("Native Gekko TA-Lib adapter unavailable"); },
    addTulipIndicator() { throw Error("Native Gekko Tulip adapter unavailable"); }
  };
  if (typeof host.init !== "function" || typeof host.check !== "function") throw Error("Strategy advice callbacks unavailable");
  host.init();
  let age = 0;
  return async (bar) => {
    decision = undefined;
    const candle = { ...bar, vwp: (bar.high + bar.low + bar.close) / 3 };
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
    strategy.calculate?.(state);
    let callbackCalled = false;
    const callback = () => { callbackCalled = true; };
    const result = strategy.onPeriod(state, callback);
    if (result?.then) await result;
    else if (strategy.onPeriod.length >= 2 && !callbackCalled && !state.in_preroll)
      throw Error("Asynchronous strategy requires its original engine");
    state.lookback.unshift(state.period);
    if (state.lookback.length > 1000) state.lookback.pop();
    if (state.in_preroll) return;
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
for (const item of inputs) {
  if (/(?:^DEBUG|^noop$|^custom$)/i.test(item.name)) {
    console.log(JSON.stringify({ id: item.id, reason: "Demonstration, no-op or control example" }));
    continue;
  }
  const relative = item.source_url.split("/blob/")[1].split("/").slice(1).join("/");
  const root = roots[item.source];
  try {
    const results = await replay(item, root, relative, config);
    const hash = createHash("sha256").update(fs.readFileSync(path.join(root, relative))).digest("hex");
    console.log(JSON.stringify({ id: item.id, hash, results }));
  } catch (error) {
    const reason = String(error.message).replace(/[\r\n].*/, "");
    console.log(JSON.stringify({ id: item.id, reason }));
  }
}
