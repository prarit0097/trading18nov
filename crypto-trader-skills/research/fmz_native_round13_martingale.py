"""Bind the archived native #5197 martingale source to the reviewed futures tapes."""

import argparse
import json
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, FEE, stamp, summarize
from research.fmz_native_expanded_replay import BLOCKS, source_config
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round6_audit import ROOT, digest

IDENT = 5197
STEM = "round13-native-martingale-complete"
PREVIOUS = "round12-atr-perpetual"
ARGS = {
    "baseSpacing": 10,
    "baseAmount": 0.01,
    "ratio": 1.1,
    "interval": 500,
    "symbol": "swap",
    "profitTarget": 10,
}
AUTHOR = "https://www.fmz.com/strategy/353659"
NOTES = (
    "Archived ETH/USDT margin grid, with separate BTC/USDT port and archived "
    "daily chart, hourly simulated ticks, 500 ms polling, and effective 20x "
    "source leverage. All native bids stayed unfilled until the source canceled "
    "them. Native cash reconciles exactly and no position opened. Win rate "
    "is undefined. This evidence applies to hourly simulation fills."
)


def stage(archive, target):
    row = next(
        r
        for r in read(ROOT / "remaining-backtest-round12-coverage.json")["disposition"]
        if r["id"] == IDENT
    )
    with ZipFile(archive) as source_zip:
        filename = unquote(row["source"].rsplit("/", 1)[-1])
        raw = source_zip.read(f"strategies-{FMZ_REF}/{filename}")
    doc = raw.decode()
    [code] = [b for tag, b in BLOCKS.findall(doc) if tag.strip() == "javascript"]
    assert "var MarginLevel=20\nexchange.SetMarginLevel(MarginLevel)" in code
    assert AUTHOR in doc and "|MarginLevel|50|" in doc
    for key, value in ARGS.items():
        assert f"|{key}|{value}|" in doc
    fields, archive_args = source_config(code)
    assert fields["period"] == "1d" and fields["basePeriod"] == "1h"
    assert not archive_args
    assert json.loads(fields["exchanges"]) == [
        {"eid": "Futures_Binance", "currency": "ETH_USDT"}
    ]
    jobs = [
        {
            **j,
            "id": IDENT,
            "source": row["source"],
            "name": row["name"],
            "source_sha256": digest(raw),
            "code": code,
            "args": ARGS,
            "fields": fields,
            "cfg": {**j["cfg"], "fee": FEE, "timeout": 210_000},
        }
        for j in read(target / (PREVIOUS + "-jobs.json"))
    ]
    worker = (target / (PREVIOUS + "-worker.cjs")).read_text(encoding="utf-8")
    worker = worker.replace(PREVIOUS, STEM).replace(
        "fee: [0.018, 0.036]", "fee: [cfg.fee * 100, cfg.fee * 100]"
    )
    x = worker.index("  let baseOverride = null;")
    y = worker.index("  const nativeSetContract = exchange.SetContractType;", x)
    worker = worker[:x] + worker[y:]
    before = worker.index("  const sleep = scope.Sleep;")
    worker = (
        worker[:before]
        + """  const observed = new Map();
  const liveOrders = new Set();
  const orderStatus = exchange.GetOrders;
  const cancel = exchange.CancelOrder;
  const submissions = ['Buy', 'Sell'];
  for (const key of submissions) {
    const submit = exchange[key];
    exchange[key] = (...args) => {
      const begin = scope.Date.now();
      if (begin >= end - 3600000) throw stop;
      const id = submit(...args);
      const submitted = scope.Date.now();
      if (id) {
        assert.ok(observed.size < 15000, 'Order observation budget reached');
        assert.ok(!observed.has(id), 'Duplicate native order ID');
        observed.set(id, {begin, submitted, firstOnBook: null, lastOnBook: null,
          removed: null, canceled: null, openReports: 0, partial: []});
      }
      return id;
    };
  }
  exchange.GetOrders = (...args) => {
    const rows = orderStatus(...args);
    const at = scope.Date.now();
    const nowPending = new Set();
    for (const o of rows || []) {
      const st = observed.get(o.Id);
      assert.ok(st, 'Untracked pending order');
      nowPending.add(o.Id);
      st.firstOnBook ??= at;
      st.lastOnBook = at;
      st.openReports++;
      if (o.DealAmount && st.partial.at(-1)?.qty !== o.DealAmount) {
        st.partial.push({at, qty: o.DealAmount, price: o.AvgPrice});
      }
    }
    for (const id of liveOrders) {
      if (!nowPending.has(id)) {
        const st = observed.get(id);
        st.removed ??= at;
        liveOrders.delete(id);
      }
    }
    for (const id of nowPending) liveOrders.add(id);
    return rows;
  };
  exchange.CancelOrder = (id, ...args) => {
    const answer = cancel(id, ...args);
    if (answer) observed.get(id).canceled = scope.Date.now();
    return answer;
  };
"""
        + worker[before:]
    )
    # Bind very short-lived immediate-order observations to the first book read.
    worker = worker.replace(
        "          removed: null, canceled: null, openReports: 0, partial: []});",
        "          removed: null, canceled: null, openReports: 0, partial: []});\n"
        "        liveOrders.add(id);",
    )
    worker = worker.replace(
        "    assert.equal(baseOverride, 'https://testnet.binancefuture.com');\n",
        "",
    ).replace("ledgerTime, baseOverride,", "ledgerTime, observations: [...observed],")
    write(target / (STEM + "-jobs.json"), jobs)
    (target / (STEM + "-worker.cjs")).write_text(worker, encoding="utf-8", newline="\n")


def check_no_fills(record, job):
    feed = job["feed"]
    start, end = (stamp(feed[k]) * 1000 for k in ("start", "end"))
    snapshot, ledger_time = (record[k] for k in ("snapshotTime", "ledgerTime"))
    assert end - 7200000 <= snapshot <= ledger_time < end
    assert not record["positions"] and record["resting"] == 0
    orders, observations = record["orders"], dict(record["observations"])
    assert len(orders) > 0 and len(orders) == len(observations)
    assert len({order["Id"] for order in orders}) == len(orders)
    delays = []
    for order in orders:
        obs = observations[order["Id"]]
        assert order["Status"] == 2 and order["Type"] == 0 and order["Offset"] == 0
        assert order["Symbol"] == feed["coin"] + "_USDT.swap"
        assert order["AvgPrice"] == order["DealAmount"] == 0 and order["Price"] > 0
        assert not obs["partial"] and obs["openReports"] >= 1
        assert (
            start
            <= obs["begin"]
            <= order["Time"]
            <= obs["submitted"]
            <= obs["firstOnBook"]
            <= obs["lastOnBook"]
            <= obs["canceled"]
            <= obs["removed"]
            <= ledger_time
        )
        delays.append(obs["canceled"] - obs["submitted"])
    account = record["account"]
    assert account["Balance"] == account["Equity"] == EQUITY
    assert all(
        account[k] == 0 for k in ("FrozenBalance", "Stocks", "FrozenStocks", "UPnL")
    )
    return {
        "submitted_and_canceled": len(orders),
        "funding_events_settled": 0,
        "gross_fills": 0,
        "cancellation_delay_ms": [min(delays), max(delays)],
        "first_order_lifecycle": observations[orders[0]["Id"]],
        "final_native_wallet": account,
        "snapshot_time": snapshot,
        "ledger_time": ledger_time,
    }


def finish(target, output):
    jobs = read(target / (STEM + "-jobs.json"))
    worker_hash = digest((target / (STEM + "-worker.cjs")).read_bytes())
    inputs = (target / f"{STEM}-js-{IDENT}.jsonl").read_bytes()
    receipts = {}
    for line in inputs.splitlines(keepends=True):
        if line.endswith(b"\n"):
            r = json.loads(line)
            assert r["worker_sha256"] == worker_hash
            receipts[r["coin"], r["start"]] = r, digest(line.rstrip())
    probe = read(target / "round3-isolation-js.json")
    assert probe["privateRead"] == "ERR_ACCESS_DENIED" and probe["network"] == "EACCES"
    evidence, verified, results, unknown = [], {}, [], set()
    for job in jobs:
        feed = job["feed"]
        key = feed["coin"], feed["start"]
        record, receipt_hash = receipts.get(key, ({}, None))
        proof = {
            "feed": feed,
            "source_sha256": job["source_sha256"],
            "code_sha256": digest(job["code"].encode()),
            "raw_receipt_sha256": receipt_hash,
        }
        try:
            if not record or record.get("reason"):
                raise ValueError(record.get("reason", "No native receipt"))
            assert record["code_sha256"] == proof["code_sha256"]
            observation = check_no_fills(record, job)
            proof.update(observation)
            verified[key] = observation["submitted_and_canceled"]
        except (AssertionError, IndexError, KeyError, TypeError, ValueError) as exc:
            proof["reason"] = str(exc) or "Independent order lifecycle check failed"
            unknown.add(proof["reason"])
        evidence.append(proof)
    if verified.keys() == KEYS:
        for start, (_, label) in WINDOWS.items():
            btc, eth = (verified[coin, start] for coin in ("BTC", "ETH"))
            for market, attempts in (
                ("BTCUSDT", btc),
                ("ETHUSDT", eth),
                ("BTCUSDT + ETHUSDT", btc + eth),
            ):
                stats = summarize(
                    (
                        "FMZ native perpetual martingale",
                        job["name"],
                        market + " perp",
                        "Archived limit-order loop",
                    ),
                    label,
                    [],
                    0,
                )
                stats.update(
                    id=IDENT,
                    source=job["source"],
                    interval="1d",
                    quote_currency="USDT",
                    submitted_and_canceled=attempts,
                )
                results.append(stats)
        status, note = "Tested · FMZ native verified no fills", NOTES
    else:
        status, note = "Pending · FMZ native martingale", " | ".join(sorted(unknown))
    write(
        output,
        {
            "coverage": [[IDENT, status, note]],
            "results": results,
            "evidence": evidence,
            "source_settings": job["fields"],
            "effective_parameters": {**ARGS, "MarginLevel": 20},
            "archived_margin_default": 50,
            "research_fee_rate": FEE,
            "isolation": probe,
            "worker_sha256": worker_hash,
            "engine_sha256": digest((target / "fmz-wasm-engine.cjs").read_bytes()),
            "proof_scope": (
                "Lifecycle taps record the result of native source calls without "
                "adding market, wallet or order queries. Every submitted bid has "
                "a sequenced on-book observation, cancellation, and removal. "
                "The observed price path is generated from archived one-hour "
                "candles and near-end snapshots are about one hour before cutoff."
            ),
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("target", type=Path)
    p.add_argument("--finish", type=Path)
    a = p.parse_args()
    if a.finish:
        finish(a.target, a.finish)
    else:
        stage(a.archive, a.target)
