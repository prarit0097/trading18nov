import fs from "node:fs";
import { pathToFileURL } from "node:url";
import { Worker, isMainThread, parentPort, workerData } from "node:worker_threads";

const GROUP = "TradingView · Binance";
const EQUITY = 10_000;
const EXECUTION = .00030;
const FEE = .00059;
const TICKS = { BTCUSD: .1, ETHUSD: .01 };
const CLOSED_FIELDS = ["entry_price", "exit_price", "entry_time", "exit_time", "size", "commission", "profit"];

function normalizedTimeframe(value) {
  return { "1D": "D", "1W": "W" }[value] ?? value;
}

function drawdown(trades, offset) {
  const byTime = new Map();
  for (const row of trades) byTime.set(row[0], (byTime.get(row[0]) ?? 0) + row[offset]);
  let equity = EQUITY, peak = EQUITY, max = 0, maxPct = 0;
  for (const time of [...byTime.keys()].sort((a, b) => a - b)) {
    equity += byTime.get(time);
    peak = Math.max(peak, equity);
    max = Math.max(max, peak - equity);
    maxPct = Math.max(maxPct, (peak - equity) / peak);
  }
  return [max, maxPct];
}

function summarize(item, period, market, sample, unresolved, interval) {
  const sums = [0, 0, 0], wins = [0, 0, 0];
  for (const row of sample) {
    for (let i = 0; i < 3; i++) {
      sums[i] += row[i + 1];
      if (row[i + 1] > 1e-9) wins[i]++;
    }
  }
  const [gross, after_fees, net] = sums;
  const [gross_dd, gross_dd_pct] = drawdown(sample, 1);
  const [fee_dd, fee_dd_pct] = drawdown(sample, 2);
  const [net_dd, net_dd_pct] = drawdown(sample, 3);
  return {
    group: GROUP, name: item.name, market, exit: "Source PineTS exits", period,
    trades: sample.length, unsettled: unresolved, gross_wins: wins[0], fee_wins: wins[1],
    net_wins: wins[2], gross, after_fees, net, fees: gross - after_fees,
    execution: after_fees - net, gross_dd, fee_dd, net_dd, gross_dd_pct, fee_dd_pct,
    net_dd_pct, id: item.id, source: item.source, source_sha256: item.hash,
    archive_interval: item.archived, interval: interval + "m"
  };
}

function forbiddenNetwork() { throw Error("External network access disabled"); }

async function runWorker() {
  globalThis.fetch = forbiddenNetwork;
  // Keep the log protocol separate from any runtime warnings.
  for (const method of ["log", "info", "warn", "error", "debug"]) console[method] = () => {};
  const { Indicator, PineTS } = await import(pathToFileURL(workerData.engine).href);
  const windows = JSON.parse(fs.readFileSync(workerData.candles, "utf8"));
  const firstWindow = Object.values(windows)[0];
  const coins = firstWindow.market ? Object.keys(firstWindow.market.symbols) : ["BTCUSD", "ETHUSD"];
  const firstBar = firstWindow[coins[0]][0][0];
  const interval = String((firstBar.closeTime - firstBar.openTime) / 60_000);
  const configs = {
    default_qty_type: "cash", default_qty_value: 1000, initial_capital: EQUITY,
    commission_type: "percent", commission_value: FEE * 100, margin_long: 0, margin_short: 0,
    slippage: 0
  };

  async function replay(indicator, windowsByCoin, symbol) {
    const sample = [];
    let unresolved = 0;
    for (const candles of windowsByCoin[symbol]) {
      const available = new Map(candles.map((row) => [row.openTime, row.volume > 0]));
      const extra = windowsByCoin.market;
      const tick = extra?.symbols[symbol].tick ?? TICKS[symbol];
      const firstTime = candles[0].openTime;
      const lastTime = candles.at(-1).closeTime;
      let missing;
      const provider = {
        configure() {},
        async getMarketData(ticker, timeframe) {
          const key = normalizedTimeframe(timeframe);
          if (ticker === symbol || (extra && ticker === extra.prefix + ":" + symbol)) {
            if (key === interval) return candles;
            const secondary = extra?.references?.[symbol]?.[key]?.filter(
              row => row.openTime >= firstTime && row.closeTime <= lastTime
            );
            if (secondary?.length) return secondary;
          }
          missing = Error("Unavailable market-data dependency: " + String(ticker) + " " + String(timeframe));
          throw missing;
        },
        async getSymbolInfo() {
          return { ticker: symbol, tickerid: symbol, currency: extra?.currency ?? "USD", basecurrency: symbol.slice(0, 3),
                   type: "crypto", timezone: "UTC", mintick: tick, pointvalue: 1,
                   mincontract: extra?.symbols[symbol].step ?? 0.00000001,
                   pricescale: Math.round(1 / tick), minmove: 1,
                   session: "24x7", prefix: extra?.prefix ?? "DELTA" };
        }
      };
      const engine = new PineTS(provider, symbol, interval, candles.length);
      engine.setFillsOnTickGrid(false);
      engine.setMaxLoops(500);
      engine.setImportResolver(null);
      const context = await engine.run(indicator);
      if (missing) throw missing;
      if (context.warnings?.length) throw Error("PineTS emitted runtime warnings");
      if (!context.strategy) throw Error("PineTS did not return a strategy ledger");
      const state = context.strategy;
      if (state.config.use_bar_magnifier || state.config.calc_on_order_fills || state.config.calc_on_every_tick)
        throw Error("Source requires intrabar evaluation or recalculation after fills");
      for (const row of state.opentrades) {
        if (!available.get(row.entry_time)) throw Error("Broker used an untraded candle");
      }
      unresolved += state.opentrades.length;
      for (const row of state.closedtrades) {
        if (!CLOSED_FIELDS.every((key) => Number.isFinite(row[key])) || row.size === 0 ||
            row.entry_time > row.exit_time || row.entry_price <= 0 || row.exit_price <= 0)
          throw Error("Invalid broker trade ledger");
        if (!available.get(row.entry_time) || !available.get(row.exit_time))
          throw Error("Broker used an untraded candle");
        const gross = row.size * (row.exit_price - row.entry_price);
        const turnover = Math.abs(row.size) * (row.exit_price + row.entry_price);
        const expected = turnover * FEE;
        if (Math.abs(expected - row.commission) > 1e-6 * Math.max(1, expected) ||
            Math.abs(row.profit - (gross - expected)) > 1e-6 * Math.max(1, Math.abs(gross)))
          throw Error("Broker fees or P&L failed independent reconciliation");
        const feeOnly = gross - expected;
        sample.push([row.exit_time, gross, feeOnly, feeOnly - turnover * EXECUTION]);
      }
    }
    return { sample, unresolved };
  }

  parentPort.on("message", async (item) => {
    try {
      const indicator = new Indicator(item.code);
      for (const [key, value] of Object.entries(configs)) if (!(item.id === 6034 && key.startsWith("default_qty"))) indicator.prop[key] = value;
      const results = [];
      for (const [period, candles] of Object.entries(windows)) {
        const btc = await replay(indicator, candles, coins[0]);
        const eth = await replay(indicator, candles, coins[1]);
        results.push(summarize(item, period, coins[0], btc.sample, btc.unresolved, interval),
                     summarize(item, period, coins[1], eth.sample, eth.unresolved, interval),
                     summarize(item, period, coins.join(" + ").includes("USDT") ? "BTCUSDT + ETHUSDT" : "BTC + ETH", [...btc.sample, ...eth.sample],
                               btc.unresolved + eth.unresolved, interval));
      }
      parentPort.postMessage({ id: item.id, results });
    } catch (error) {
      const message = String(error?.message ?? error);
      const reason = message.split("\n")[0];
      parentPort.postMessage({ id: item.id, reason });
    }
  });
  parentPort.postMessage({ ready: true });
}

function runBatch() {
  const [input, candles, engine, configured = "6"] = process.argv.slice(2);
  const entries = JSON.parse(fs.readFileSync(input, "utf8"));
  const concurrency = Math.min(entries.length, Number(configured));
  const timeLimit = 14_000;
  let cursor = 0, count = 0;

  function slot() {
    let work, timer, retired = false, usage = 0;
    const worker = new Worker(new URL(import.meta.url), {
      workerData: { candles, engine }, resourceLimits: { maxOldGenerationSizeMb: 448 }
    });
    function settle(record) {
      clearTimeout(timer);
      work = undefined;
      process.stdout.write(JSON.stringify(record) + "\n");
      if (++count % 200 === 0) process.stderr.write("PineTS evaluated " + count + " / " + entries.length + "\n");
    }
    function retire(reason) {
      if (retired) return;
      retired = true;
      if (work) settle({ id: work.id, reason });
      worker.terminate().then(() => { if (cursor < entries.length) slot(); });
    }
    function next() {
      if (cursor >= entries.length || usage >= 30) { retire(); return; }
      work = entries[cursor++];
      usage++;
      timer = setTimeout(() => retire("PineTS per-source time or memory budget exceeded"), timeLimit);
      worker.postMessage(work);
    }
    worker.on("message", (record) => {
      if (retired) return;
      if (!record.ready) settle(record);
      next();
    });
    worker.on("error", () => retire("PineTS worker terminated during replay"));
    worker.on("exit", (code) => {
      if (!retired && code !== 0 && !work) throw Error("PineTS worker could not initialize");
      if (!retired) retire("PineTS worker exited during replay");
    });
  }

  for (let i = 0; i < concurrency; i++) slot();
}

if (isMainThread) runBatch();
else await runWorker();
