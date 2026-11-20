"""Stage source-pinned legacy FMZ spot ports on reviewed BTC and ETH tapes."""

import argparse
import json
from collections import deque
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import (
    EQUITY,
    EXECUTION,
    FEE,
    drawdown,
    stamp,
    summarize,
)
from research.fmz_native_expanded_replay import BLOCKS
from research.fmz_native_round3 import KEYS
from research.fmz_native_round6_audit import ROOT, digest
from research.fmz_native_round6_replay import public_settings
from research.fmz_native_round7 import file_opening

STEM = "round14-legacy-spot-timed"
AUTHORS = {1847: 2406, 4978: 9929}


def bind(archive, public, ident):
    row = next(
        r
        for r in read(ROOT / "remaining-backtest-round12-coverage.json")["disposition"]
        if r["id"] == ident
    )
    with ZipFile(archive) as source_zip:
        filename = unquote(row["source"].split("/")[-1])
        raw = source_zip.read(f"strategies-{FMZ_REF}/{filename}")
    doc = raw.decode()
    [code] = [b for tag, b in BLOCKS.findall(doc) if tag.strip() == "javascript"]
    publisher = f"https://www.fmz.com/strategy/{AUTHORS[ident]}"
    assert publisher in doc
    params = public_settings(
        public / f"{AUTHORS[ident]}.html", {"code": code, "parameter_page": publisher}
    )
    assert "|OpType|0|" in doc and "|OpMode|0|" in doc and "|RestoreType|0|" in doc
    args = {**params["args"], "OpType": 0, "OpMode": 0, "RestoreType": 0}
    assert args["Interval"] == args["AddGoal"] == 1 and args["OpAmount"] == 0.1
    assert args["RestoreIt"] is False and args["SaveLocal"] is False
    assert 'exchange.GetName().indexOf("Future")' in code and "GetRecords" not in code
    seed_base, seed_quote = (0.1, EQUITY) if ident == 1847 else (31, 100001)
    if ident == 1847:
        assert args["AutoReverse"] is True
    else:
        assert args["StopLoss"] == 8
        page = (public / f"{AUTHORS[ident]}.html").read_text(encoding="utf-8")
        assert "10万以上" in page and "30以上" in page
    return row, digest(raw), code, args, params, seed_base, seed_quote


def stage(archive, public, target):
    books = {}
    for job in read(target / "round5-native-javascript-jobs.json"):
        feed = job["feed"]
        if feed["base_seconds"] == 300:
            books.setdefault((feed["coin"], feed["start"]), feed)
    assert set(books) == KEYS
    jobs = []
    for ident in AUTHORS:
        row, source_sha, code, args, params, base, cash = bind(archive, public, ident)
        for key in sorted(KEYS):
            common = books[key]
            market = {name: common[name] for name in ("file", "sha256")}
            feed = {
                **common,
                "market": market,
                "step": 300,
                "base": "5m",
                "period": "15m",
                "eid": "Binance",
            }
            seed = {**file_opening(target, feed, {"stocks": base}, ident), "cash": cash}
            assert digest((target / feed["file"]).read_bytes()) == feed["sha256"]
            jobs.append(
                {
                    "id": ident,
                    "source": row["source"],
                    "name": row["name"],
                    "code": code,
                    "args": args,
                    "source_sha256": source_sha,
                    "public": params,
                    "cfg": {
                        "fee": FEE,
                        "balance": cash,
                        "opening": seed,
                        "timeout": 180_000,
                    },
                    "feed": feed,
                }
            )
    worker = (
        (target / "round6-native-worker.cjs")
        .read_text(encoding="utf-8")
        .replace("round6-native", STEM)
    )
    marker = "  const exchange = scope.exchange;"
    assert worker.count(marker) == 1
    worker = worker.replace(
        marker,
        marker
        + """
  if (!exchange.GetRate) {
    exchange.GetRate = () => 1;
    exchange.SetRate = rate => assert.equal(rate, 1, 'Unexpected quote currency conversion');
  }
""",
    )
    marker = "    let stopped = false;"
    assert worker.count(marker) == 1
    worker = worker.replace(
        marker,
        """    const recent = [];
    const lastPending = new Map();
    const finalIntervals = new Map();
    const nativeOrders = exchange.GetOrders;
    exchange.GetOrders = (...params) => {
      const rows = nativeOrders(...params);
      if (!rows) return rows;
      const at = scope.Date.now(), pending = new Set();
      for (const row of rows) {
        if (row.DealAmount) throw Error('Partial native market fill requires order-level execution times');
        pending.add(row.Id);
        lastPending.set(row.Id, at);
      }
      for (const [id, from] of lastPending) {
        if (!pending.has(id)) {
          finalIntervals.set(id, [from, at]);
          lastPending.delete(id);
        }
      }
      return rows;
    };
    const attempts = {accepted: 0, rejected: 0};
    for (const kind of ['Buy','Sell']) {
      const order = exchange[kind];
      exchange[kind] = (price, amount, ...note) => {
        const id = order(price, amount, ...note);
        if (id) lastPending.set(id, scope.Date.now());
        attempts[id ? 'accepted' : 'rejected']++;
        if (recent.length === 12) recent.shift();
        recent.push({kind, price, amount, id: id || null, time: scope.Date.now()});
        return id;
      };
    }
    let stopped = false, sourceFailure = null;
""",
    )
    worker = worker.replace(
        "      if (error !== stop) throw error;\n      stopped = true;",
        """      if (error === stop) stopped = true;
      else if (error === '下单失败' || error === '出师不利, 开仓失败') sourceFailure = error;
      else throw error;
""",
    ).replace(
        "    if (!stopped && scope.Date.now()",
        "    if (!stopped && !sourceFailure && scope.Date.now()",
    )
    worker = worker.replace(
        "    assert.ok(end - feed.step * 1000 <= last.Time && last.Time <= end",
        "    assert.ok(sourceFailure || (end - feed.step * 1000 <= last.Time && last.Time <= end)",
    )
    worker = (
        worker.replace(
            "    const endOrders = [];",
            "    const endOrders = [];\n"
            "    const orderDigest = createHash('sha256');\n"
            "    let observedHistoryOrders = 0;",
        )
        .replace(
            "for (let page = 0; page < 100; page++)",
            "for (let page = 0; page < 1500; page++)",
        )
        .replace(
            "      endOrders.push(...orders);",
            """      observedHistoryOrders += orders.length;
      orderDigest.update(JSON.stringify(orders));
      endOrders.push(...orders.filter(o => o.DealAmount > 0));
      assert.ok(endOrders.length <= 60000, 'Filled-order evidence exceeds available disk budget');""",
        )
        .replace("assert.ok(page < 99,", "assert.ok(page < 1499,")
    )
    worker = worker.replace(
        "    return {last, snapshotTime,",
        "    return {sourceFailure, recent, attempts, observedHistoryOrders, "
        "historySha256: orderDigest.digest('hex'), "
        "fillIntervals: endOrders.filter(o => o.DealAmount).map(o => [o.Id, finalIntervals.get(o.Id)]), "
        "last, snapshotTime,",
    )
    write(target / (STEM + "-jobs.json"), jobs)
    (target / (STEM + "-worker.cjs")).write_text(worker, encoding="utf-8", newline="\n")


def realized_orders(orders, intervals, seed, buy_first):
    lots = deque([(seed["base"], seed["price"], False)])
    priority = 1 if buy_first else -1
    ordered = sorted(
        orders, key=lambda o: (intervals[o["Id"]][1], priority * o["Type"], o["Id"])
    )
    result = []
    for order in ordered:
        qty, price = order["DealAmount"], order["AvgPrice"]
        if order["Type"] == 0:
            lots.append((qty, price, True))
            continue
        gross = purchase_turnover = 0.0
        sale_turnover = qty * price
        while qty > 1e-9:
            size, basis, purchased = lots.popleft()
            matched = min(size, qty)
            gross += matched * (price - basis)
            if purchased:
                purchase_turnover += matched * basis
            qty -= matched
            if size - matched > 1e-9:
                lots.appendleft((size - matched, basis, purchased))
        turnover = sale_turnover + purchase_turnover
        fee_only = gross - turnover * FEE
        result.append(
            (
                intervals[order["Id"]][1],
                gross,
                fee_only,
                fee_only - turnover * EXECUTION,
            )
        )
    return result, sum(purchased for _, _, purchased in lots)


def reconcile(record, job):
    feed, seed = job["feed"], job["cfg"]["opening"]
    start, end = (stamp(feed[name]) * 1000 for name in ("start", "end"))
    at = record["snapshotTime"]
    assert seed["timestamp"] < start <= at <= end
    if not record["sourceFailure"]:
        assert end - 60_000 <= at
    assert (
        record["observedHistoryOrders"] + record["resting"]
        == record["attempts"]["accepted"]
    )
    orders = [o for o in record["orders"] if o["DealAmount"]]
    intervals = dict(record["fillIntervals"])
    assert len(orders) == len(intervals) and len({o["Id"] for o in orders}) == len(
        orders
    )
    cash, base = seed["cash"], seed["base"]
    time_groups, width = {}, []
    last_end = previous_end = 0
    for order in sorted(orders, key=lambda o: intervals[o["Id"]][1]):
        oid, qty, p = (order[k] for k in ("Id", "DealAmount", "AvgPrice"))
        a, b = intervals[oid]
        assert start <= order["Time"] <= a < b <= end
        assert (
            order["Status"] == 1 and order["Price"] > 0 and order["Amount"] == qty > 0
        )
        assert order["Symbol"] == feed["coin"] + "_USDT"
        assert order["Type"] in (0, 1) and p > 0
        if b != last_end:
            previous_end, last_end = last_end, b
        assert a >= previous_end, (
            "Overlapping distinct observations require full fill time"
        )
        time_groups.setdefault(b, []).append(order["Type"])
        assert len(time_groups[b]) <= 2 and len(set(time_groups[b])) == len(
            time_groups[b]
        )
        width.append(b - a)
        if order["Type"] == 0:
            cash -= qty * p * (1 + FEE)
            base += qty
        else:
            cash += qty * p * (1 - FEE)
            base -= qty
    ledger, unsettled = realized_orders(orders, intervals, seed, True)
    assert (ledger, unsettled) == realized_orders(orders, intervals, seed, False)
    account = record["account"]
    cash_error = cash - account["Balance"] - account["FrozenBalance"]
    asset_error = base - account["Stocks"] - account["FrozenStocks"]
    assert abs(cash_error) < 1e-7 and abs(asset_error) < 1e-9
    initial_equity = seed["cash"] + seed["base"] * seed["price"]
    mark = record["last"]["Last"]
    proof = {
        "post_fee_wallet_value_at_native_quote": cash + base * mark,
        "post_fee_marked_pnl_at_observation": cash + base * mark - initial_equity,
        "cash_error": cash_error,
        "stock_error": asset_error,
        "filled_orders": len(orders),
        "closed_sell_orders": len(ledger),
        "new_inventory_lots_unsettled": unsettled,
        "ambiguous_opposite_side_groups": sum(
            len(v) == 2 for v in time_groups.values()
        ),
        "within_group_fifo_sensitivity": "Identical realized series in both feasible orders",
        "fill_bracket_ms_min_max": [min(width, default=0), max(width, default=0)],
    }
    return ledger, initial_equity, proof


def finish(target, output):
    jobs = read(target / (STEM + "-jobs.json"))
    worker_hash = digest((target / f"{STEM}-worker.cjs").read_bytes())
    probe = read(target / "round3-isolation-js.json")
    assert probe["privateRead"] == "ERR_ACCESS_DENIED" and probe["network"] == "EACCES"
    records, prior = {}, {}
    diagnostic = target / "round14-legacy-spot-diagnostic-js-1847-4978.jsonl"
    if diagnostic.is_file():
        with diagnostic.open("rb") as stream:
            for raw in stream:
                r = json.loads(raw)
                prior[r["id"], r["coin"], r["start"]] = r["historySha256"]
        assert len(prior) == 8
    latest = target / f"{STEM}-js-1847-4978.jsonl"
    with latest.open("rb") as stream:
        for raw in stream:
            r = json.loads(raw)
            key = r["id"], r["coin"], r["start"]
            assert r["worker_sha256"] == worker_hash
            if prior:
                assert r["historySha256"] == prior[key]
            records[key] = r, digest(raw.rstrip())
    assert len(records) == len(jobs) == 8
    evidence, scope_results = [], []
    for job in jobs:
        feed, ident = job["feed"], job["id"]
        r, receipt = records[ident, feed["coin"], feed["start"]]
        assert r["code_sha256"] == digest(job["code"].encode())
        assert digest((target / feed["file"]).read_bytes()) == feed["sha256"]
        ledger, equity, proof = reconcile(r, job)
        common = {
            "id": ident,
            "source": job["source"],
            "market": feed["coin"] + "USDT spot",
            "period": "Reference" if feed["start"] == "2026-09-23" else "Later",
        }
        evidence.append(
            {
                **common,
                "archive_sha256": job["source_sha256"],
                "code_sha256": r["code_sha256"],
                "market_sha256": feed["sha256"],
                "raw_receipt_sha256": receipt,
                "native_order_page_digest": r["historySha256"],
                "market_tape": feed["market"],
                "opening_inventory": job["cfg"]["opening"],
                "author_parameter_receipt": job["public"],
                "parameters": job["args"],
                "native_source_abort": r["sourceFailure"],
                "snapshot_time": r["snapshotTime"],
                "native_price_observation_time": r["last"]["Time"],
                "native_price_observation": r["last"]["Last"],
                "native_closing_account": r["account"],
                "final_order_attempts": r["recent"],
                "submission_totals": r["attempts"],
                "verification": proof,
            }
        )
        if r["sourceFailure"]:
            continue
        metrics = summarize(
            (
                "FMZ native legacy spot variant",
                job["name"],
                common["market"],
                "Archived Icebreaker",
            ),
            common["period"],
            ledger,
            proof["new_inventory_lots_unsettled"],
        )
        ratio = EQUITY / equity
        for name, i in (("gross", 1), ("fee", 2), ("net", 3)):
            dd, pct = drawdown((step[0], step[i] * ratio) for step in ledger)
            metrics[name + "_dd"], metrics[name + "_dd_pct"] = dd / ratio, pct
        metrics.update(
            common, starting_equity=equity, quote_currency="USDT", interval="15m"
        )
        scope_results.append(metrics)
    assert len(scope_results) == 3 and {s["id"] for s in scope_results} == {4978}
    write(
        output,
        {
            "coverage": [
                [
                    1847,
                    "Pending · FMZ authored order-failure exits",
                    "All four BTC/ETH spot sessions ended when the unchanged archived program raised an order failure. Native fill ordering and settlement reconcile before each abort. A full performance comparison remains unavailable.",
                ],
                [
                    4978,
                    "Tested · Verified three complete scopes",
                    "BTC Reference/Later and ETH Later completed with independently reconciled fills. ETH Reference ended on the published order-failure branch. There is no combined result or performance claim for the aborted scope.",
                ],
            ],
            "results": scope_results,
            "native_evidence": evidence,
            "worker_sha256": worker_hash,
            "isolation_probe": probe,
            "diagnostic_order_page_identity_verified": bool(prior),
            "execution_model": {
                "fee_each_side": FEE,
                "slippage_each_side": EXECUTION,
                "scope": "Binance spot port treating archived numeric currency distances as nominal USDT amounts, without historical CNY conversion.",
                "attribution": "Per native sell order across FIFO lots. Match outcomes by nonoverlapping native book observation groups and verify both within-group fill orders produce exactly the same series.",
                "starting_assets": "Mark pre-window seeded stock at the last closed bar. No modeled entry fee or friction on seeded inventory. The 4978 scenario follows the publisher's capital and inventory ranges.",
                "aborted_scopes": "No post-abort extrapolation or performance rows for the five incomplete scopes.",
            },
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("public", type=Path)
    p.add_argument("target", type=Path)
    p.add_argument("--finish", type=Path)
    a = p.parse_args()
    if a.finish:
        finish(a.target, a.finish)
    else:
        stage(a.archive, a.public, a.target)
