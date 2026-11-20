"""Test the FMZ AHR999 BTC rule with public author settings and daily Binance data."""

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.fmz_native_public_params import StrategyPage, normalized
from research.nonpine_round4_metrics import metrics
from research.nonpine_round7_ladders import floor_lot
from research.nonpine_round9_dip import BUFFER, FEE, LOTS, utc_day

ID = 1091
WINDOWS = (("2018-04-14", "2021-07-18"), ("2021-07-18", "2024-10-21"))
PUBLISHER = "https://www.fmz.com/strategy/299799"
FIELDS = ("InitMoney", "Interval", "Money", "Top", "Bottom", "Multiple", "TakeProfit", "TakeProfitLine", "TakeProfitRate")


def validate_settings(body, html):
    page = StrategyPage()
    page.feed(html.decode("utf-8"))
    original = normalized(body.decode("utf-8"))
    preview = next(normalized(text) for text in page.previews if text.lstrip().startswith("/*backtest"))
    signature = re.compile(r"^(.+?@Author:\s+RedSword)\s+<")
    common = signature.match(original).group(1)
    assert common == signature.match(preview).group(1)
    config = {field: page.values[field] for field in FIELDS}
    assert config["Interval"] == 24 and config["TakeProfit"] is True
    assert config["InitMoney"] == 1_000_000 and 0 < config["Bottom"] < config["Top"]
    return config, len(common)


def data(root):
    receipt = json.loads((root / "manifest.json").read_bytes())
    rows = []
    for name, item in sorted(receipt.items()):
        raw = (root / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        part = json.loads(raw)
        assert len(part) == item["rows"]
        for stamp, opn, high, low, close, volume, *_ in part:
            assert stamp % 86_400_000 == 0 and float(low) <= min(float(opn), float(close))
            assert max(float(opn), float(close)) <= float(high) and float(volume) > 0
            rows.append((stamp // 1000, float(opn), float(close), float(volume)))
    assert all(t[0] - r[0] == 86400 for r, t in zip(rows, rows[1:]))
    return rows, receipt


def index(close_buffer, timestamp, opn):
    reference = len(close_buffer) + 1
    harmonic = reference / (sum(1 / px for px in close_buffer) + 1 / opn)
    age = (timestamp - 1230940800) // 86400
    a, b = (5.8, -16.88) if timestamp > 1587014160 else (5.84, -17.01)
    trend = 10 ** (a * math.log10(age) + b)
    score, inverse = (opn / harmonic) * (opn / trend), (harmonic / opn) * (trend / opn) * 3
    return tuple(math.floor(v * 1000 + 0.5) / 1000 for v in (score, inverse))


def marked_drawdown(rows, start, end, capital, entries, exits):
    buys = {event[0]: event for event in entries}
    sales = {event[0]: event for event in exits}
    cash, base, costs = capital, 0.0, 0.0
    peak, max_drop, max_fraction = capital, 0.0, 0.0
    for at, opn, close, _ in rows:
        if at < start:
            continue
        if at >= end:
            break
        if entry := buys.get(at):
            spent = entry[3] * opn
            cash -= spent
            base += entry[4]
            costs += spent * BUFFER
        if sale := sales.get(at):
            proceeds = sale[3] * opn
            cash += proceeds * (1 - FEE)
            base -= sale[3]
            costs += proceeds * BUFFER
        value = cash + base * close - costs
        peak = max(peak, value)
        max_drop = max(max_drop, peak - value)
        max_fraction = max(max_fraction, (peak - value) / peak)
    return {"quote": max_drop, "fraction": max_fraction}


def replay(rows, start, end, cfg):
    capital, unit = float(cfg["InitMoney"]), cfg["Money"]
    cash, base, number = capital, 0.0, 0
    history, inventory = deque(maxlen=199), deque()
    entries, exits, closed, rejected = [], [], [], defaultdict(int)
    mark = None
    for timestamp, opn, close, volume in rows:
        if timestamp < start:
            history.append(close)
            continue
        if timestamp >= end:
            break
        assert len(history) == 199
        score, inverse = index(history, timestamp, opn)
        history.append(close)
        mark = close
        multiple = cfg["Multiple"] if score < cfg["Bottom"] else int(score < cfg["Top"])
        budget = unit * multiple
        if budget > cash:
            rejected["insufficient_quote"] += 1
            continue
        if multiple:
            quantity = floor_lot(budget / opn, LOTS["BTCUSDT"])
            assert quantity <= volume
            cash -= quantity * opn
            received = quantity * (1 - FEE)
            base += received
            number += multiple
            inventory.append([timestamp, received, opn])
            entries.append([timestamp, score, opn, quantity, received, number])
        if inverse >= cfg["TakeProfitLine"]:
            continue
        requested = floor_lot(number * cfg["TakeProfitRate"] * unit / opn, LOTS["BTCUSDT"])
        if requested <= 0 or requested > min(base, volume):
            rejected["insufficient_sell_inventory_or_volume"] += 1
            continue
        exits.append([timestamp, inverse, opn, requested])
        cash += requested * opn * (1 - FEE)
        base -= requested
        while requested > 1e-10:
            _, remaining, entry = inventory[0]
            portion = min(remaining, requested)
            gross = portion * (opn - entry)
            fees = portion * FEE * (opn + entry / (1 - FEE))
            friction = portion * BUFFER * (opn + entry / (1 - FEE))
            closed.append((timestamp, gross, fees, friction))
            requested -= portion
            inventory[0][1] -= portion
            if inventory[0][1] < 1e-10:
                inventory.popleft()
    assert mark and cash >= 0 and math.isclose(base, sum(lot[1] for lot in inventory), abs_tol=1e-8)
    m = metrics(closed, len(inventory))
    moves = defaultdict(float)
    for at, g, fee, cost in closed:
        moves[at] += g - fee - cost
    equity, top, net_dd_pct = capital, capital, 0.0
    for at in sorted(moves):
        equity += moves[at]
        top = max(top, equity)
        net_dd_pct = max(net_dd_pct, (top - equity) / top)
    m["net_dd_pct"] = net_dd_pct
    return m, {
        "entries": entries, "exits": exits, "settled": closed, "rejected": dict(rejected),
        "remaining_quote": cash, "remaining_btc": base, "closing_mark": mark, "open_lots": list(inventory),
        "marked_equity_after_fees": cash + base * mark,
        "marked_equity_after_costs": cash + base * mark - BUFFER * (
            sum(x[2] * x[3] for x in entries) + sum(x[2] * x[3] for x in exits)
        ),
        "marked_daily_after_cost_drawdown": marked_drawdown(rows, start, end, capital, entries, exits),
    }


def run(archive, backlog, page, inputs, target):
    row = json.loads(backlog.read_bytes())[str(ID)]
    pin, filename = unquote(row["source"].split("/blob/", 1)[1]).split("/", 1)
    with ZipFile(archive) as z:
        original = z.read(f"strategies-{pin}/{filename}")
    [body] = re.findall(rb"```\s*javascript\s*\n(.*?)```", original, re.S)
    assert all(token in body for token in (
        b'exchange.GetCurrency().indexOf("BTC_USD")', b"SetMaxBarLen(200)", b"Global.number * TakeProfitRate * Money"
    ))
    html = page.read_bytes()
    cfg, match_size = validate_settings(body, html)
    rows, archives = data(inputs)
    results, observations = [], {}
    for first, last in WINDOWS:
        stats, ledger = replay(rows, utc_day(first), utc_day(last), cfg)
        observations[first] = ledger
        results.append({
            "id": ID, "period": f"{first} to {last} UTC", "group": "FMZ AHR999 · daily historical sampling",
            "market": "BTCUSDT", "currency": "USDT", "interval": "1d",
            "archive_interval": "1d and 24h authored schedule", "order_family": "Market accumulation and partial sale",
            "exit": "Archived AHR999X threshold", **stats,
        })
        print(first, len(ledger["entries"]), len(ledger["exits"]), stats["trades"], stats["net"], flush=True)
    assert any(r["trades"] > 0 for r in results)
    target.write_text(json.dumps({
        "coverage": [[ID, "Tested · BTC-only AHR999 daily historical sampling",
                      "Public author settings restored. Replayed the exact native date range and an equal-length Binance BTC spot study. Source rejects other assets."]],
        "results": results, "observations": observations, "settings": cfg,
        "source": row["source"], "source_sha256": hashlib.sha256(original).hexdigest(),
        "publisher": PUBLISHER, "publisher_sha256": hashlib.sha256(html).hexdigest(),
        "preview_prefix_match_excluding_redacted_contact": match_size,
        "data": archives,
        "assumptions": [
            "The complete prefix through the author name is the same in the pinned archive and public form. The source viewer redacts the contact string. Parameters come from that public form.",
            "Each 24h decision is sampled at the first daily Binance trade, using 199 already closed daily bars plus the then-observed open for the new bar. This does not claim user-clock or intraday simulator parity.",
            "Market orders use the observed open and require available wallet and reported volume. BTC increments are modeled at 0.00001. Fees are modeled at 10 bp per side and execution friction at 3 bp per side.",
            "Fees change available inventory and cash. Friction is applied as a separate accounting overlay. Sold FIFO portions produce realized win rates, P&L and drawdown. The evidence separately measures daily marked equity drawdown and ending value.",
        ],
    }, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("archive", "backlog", "page", "inputs", "target"):
        parser.add_argument(arg, type=Path)
    opts = parser.parse_args()
    run(opts.archive, opts.backlog, opts.page, opts.inputs, opts.target)
