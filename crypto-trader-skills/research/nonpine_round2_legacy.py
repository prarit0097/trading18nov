"""Prepare Binance spot bars and reconcile isolated legacy bot callbacks."""

import csv
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from research.nonpine_round2_deribit import WINDOWS, epoch, summary

BASE = Path(__file__).resolve().parent
FEE = 0.00059
EXECUTION = 0.00030
STAKE = 1000
BAR_MS = 15 * 60000


def stock(work):
    baseline = json.loads((BASE / "remaining-backtest-coverage.json").read_bytes())
    pending = {
        r["id"] for r in baseline["disposition"] if not r["status"].startswith("Tested")
    }
    with (BASE / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream:
        return {
            i: dict(r, id=i)
            for i, r in enumerate(csv.DictReader(stream), 1)
            if i in pending and r["source"] in ("gekko", "zenbot")
        }


def prepare(work):
    dst = work / "round2"
    dst.mkdir(exist_ok=True)
    entries = stock(work)
    assert len(entries) == 21
    (dst / "legacy-candidates.json").write_text(
        json.dumps(list(entries.values())), encoding="utf-8"
    )
    for family, prefixes in [
        ("zenbot", ("lib/", "extensions/strategies/")),
        ("gekko", ("strategies/", "config/")),
    ]:
        with ZipFile(work / "legacy" / f"{family}.zip") as archive:
            for name in archive.namelist():
                if "/" not in name or name.endswith("/"):
                    continue
                rel = name.split("/", 1)[1]
                if rel.startswith(prefixes):
                    target = dst / family / rel
                    target.parent.mkdir(exist_ok=True, parents=True)
                    target.write_bytes(archive.read(name))
    using = json.loads((BASE / "nonpine_replay.json").read_bytes())["market_data"]
    windows = {label: {} for label in WINDOWS}
    for coin in ("BTC", "ETH"):
        groups = defaultdict(list)
        for file in sorted((work / "binance").glob(f"klines-spot-{coin}USDT-1m-*.zip")):
            if "-08." in file.name:
                continue
            assert (
                hashlib.sha256(file.read_bytes()).hexdigest()
                == using[file.name]["sha256_or_error"]
            )
            with (
                ZipFile(file) as archive,
                archive.open(archive.namelist()[0]) as stream,
            ):
                for line in csv.reader(bytes_.decode() for bytes_ in stream):
                    if not line[0].isdigit():
                        continue
                    t = int(line[0]) // 1000
                    groups[t // BAR_MS * BAR_MS].append((t, *map(float, line[1:6])))
        for period, dates in WINDOWS.items():
            first, end = map(epoch, dates)
            bars = []
            for ts in range(first, end, BAR_MS):
                g = sorted(groups[ts])
                assert len(g) == 15 and all(
                    x[0] == ts + i * 60000 and x[5] > 0 for i, x in enumerate(g)
                )
                bars.append(
                    dict(
                        openTime=ts,
                        closeTime=ts + BAR_MS,
                        open=g[0][1],
                        high=max(x[2] for x in g),
                        low=min(x[3] for x in g),
                        close=g[-1][4],
                        volume=sum(x[5] for x in g),
                    )
                )
            windows[period][coin] = [bars]
    (dst / "candles.json").write_text(
        json.dumps(windows, separators=(",", ":")), encoding="utf-8"
    )


def trade(row):
    event, start, end = row
    assert start > 0 and end > 0
    qty = STAKE / start
    gross = qty * (end - start)
    size = qty * (start + end)
    fee = gross - size * FEE
    return event, gross, fee, fee - size * EXECUTION


def finish(work):
    entries = stock(work)
    dst = work / "round2"
    with (dst / "legacy-out.jsonl").open("w", encoding="utf-8") as out:
        for line in (
            (dst / "legacy-raw.jsonl").read_text(encoding="utf-8-sig").splitlines()
        ):
            result = json.loads(line)
            ident = result["id"]
            item = entries[ident]
            if records := result.get("results"):
                rows = []
                records = {
                    (t["period"], t["symbol"]): (
                        [trade(x) for x in t["trades"]],
                        t["unsettled"],
                    )
                    for t in records
                }
                for period in WINDOWS:
                    btc, eth = [records[period, code] for code in ("BTC", "ETH")]
                    for market, ledger, unsettled in [
                        ("BTC/USDT", *btc),
                        ("ETH/USDT", *eth),
                        ("BTC + ETH", btc[0] + eth[0], btc[1] + eth[1]),
                    ]:
                        row = summary(ident, item, market, period, ledger, unsettled)
                        row.update(
                            group="Legacy bot callback replay · Binance",
                            exit="Pinned source sell advice",
                            interval="15m",
                            archive_interval="15m study interval",
                            venue="Binance spot",
                            currency="USDT",
                            source_sha256=result["hash"],
                        )
                        rows.append(row)
                result = dict(id=ident, results=rows)
            out.write(json.dumps(result, allow_nan=False) + "\n")


if __name__ == "__main__":
    {"prepare": prepare, "finish": finish}[sys.argv[1]](Path(sys.argv[2]))
