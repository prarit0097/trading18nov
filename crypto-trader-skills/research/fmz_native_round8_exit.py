"""Stage the original Bitfinex daily MACD exit with source-backed inventory."""

import argparse
import ast
import json
from itertools import pairwise
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_native_round3 import WINDOWS
from research.fmz_native_round5 import replace_once
from research.fmz_native_round6_audit import BASE, ROOT, digest
from research.fmz_native_round7 import (
    display_settings,
    file_opening,
    finish,
    header_settings,
    source,
)

IDENT = 575
STEM = "round8-bitfinex-hourly-verified"
WORKER = "fmz_native_round8_hourly_verified_exit_worker.py"


def worker_text(base):
    exact = '        assert q["event"][0] in ("feed", "fill") and int(q["period"][0]) == feed["base_seconds"] * 1000, url'
    code = replace_once(
        base,
        "    requests = []\n",
        """    raw_daily = (ROOT / options["daily"]["file"]).read_bytes()
    assert hashlib.sha256(raw_daily).hexdigest() == options["daily"]["sha256"]
    daily = json.loads(raw_daily)
    assert daily["detail"]["symbol"] == history["detail"]["symbol"] == feed["symbol"]
    requests = []
""",
    )
    code = replace_once(
        code,
        exact,
        """        step = int(q["period"][0])
        assert q["event"][0] in ("feed", "fill"), url
        if q["event"][0] == "fill" and step == 86400000:
            chart = daily
        else:
            assert step == feed["base_seconds"] * 1000, url
            chart = history""",
    )
    code = replace_once(
        code,
        '        step = feed["base_seconds"] * 1000\n        assert history["data"][0][0] <= start + step - 1 and history["data"][-1][0] >= stop - step, url\n',
        '        assert chart["data"][0][0] <= start + step - 1 and chart["data"][-1][0] >= stop - step, url\n',
    )
    code = replace_once(
        code,
        '{**history, "data": [r for r in history["data"] if start <= r[0] <= stop]}',
        '{**chart, "data": [r for r in chart["data"] if start <= r[0] <= stop]}',
    )
    code = replace_once(code, "import time\n", "import time\nimport traceback\n")
    code = replace_once(
        code,
        'f"{type(exc).__name__}: {exc}"[:650]',
        'f"{type(exc).__name__}: {exc} (line {traceback.extract_tb(exc.__traceback__)[-1].lineno})"[:650]',
    )
    code = code.replace("Binance", "Bitfinex").replace(
        "round7-native-python-", STEM + "-"
    )
    code = replace_once(
        code,
        '        runtime["Sleep"] = sleep\n',
        """        runtime["Sleep"] = sleep
        sell_order = venue.Sell

        def accepted_sale(*args):
            order_id = sell_order(*args)
            assert order_id, "Native engine rejected the strategy's source-sized exit"
            return order_id

        venue.Sell = accepted_sale

        original_records = venue.GetRecords
        quote = 10 ** daily["detail"]["quotePrecision"]
        hourly_closes = {r[0]: r[4] / quote for r in history["data"]}
        verified_days = set()

        def verified_records(*args, **kwargs):
            records = original_records(*args, **kwargs)
            assert len(records) >= 80, "Daily MACD warm-up was incomplete"
            last, prior = records[-1], records[-2]
            assert last["Time"] - prior["Time"] == 86400000, "Records are not daily"
            when = prior["Time"]
            expected = hourly_closes[when + 86400000 - 3600000]
            assert math.isclose(prior["Close"], expected, rel_tol=0, abs_tol=1/quote), (when, prior["Close"], expected)
            verified_days.add(when)
            return records

        venue.GetRecords = verified_records
""",
    )
    code = replace_once(
        code,
        "        snapshot_time = unix_ns() // 1_000_000\n",
        """        assert stopped and calls >= (end - begin) // 3600000 - 1
        assert len(verified_days) >= (end - begin) // 86400000 - 1, "Independent daily observations incomplete"
        snapshot_time = unix_ns() // 1_000_000
""",
    )
    ast.parse(code)
    return code


def validated_chart(work, filename, metadata, seconds, allow_sparse_before=None):
    content = (work / filename).read_bytes()
    assert digest(content) == metadata["sha256"]
    chart = json.loads(content)
    rows = chart["data"]
    assert len(rows) == metadata["rows"]
    assert all(
        b[0] - a[0] == seconds * 1000
        or (
            allow_sparse_before is not None
            and b[0] < allow_sparse_before
            and b[0] > a[0]
            and (b[0] - a[0]) % (seconds * 1000) == 0
        )
        for a, b in pairwise(rows)
    )
    assert all(row[5] > 0 for row in rows)
    return chart, content


def stage(archive, target, work):
    catalogue = next(r for r in read(BASE)["disposition"] if r["id"] == IDENT)
    bound = next(
        r
        for r in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
        if r["id"] == IDENT
    )
    with ZipFile(archive) as pinned:
        document, original = source(pinned, catalogue["source"])
    assert digest(document) == bound["document_sha256"]
    public = display_settings(work, IDENT, original)
    clean, seed = header_settings(original)
    assert public["args"] == {"num": 0.1} and seed == {"stocks": 10}
    code = replace_once(clean, "Sleep(1000*60)", "Sleep(1000*3600)")
    item = {
        "id": IDENT,
        "name": catalogue["name"],
        "source": catalogue["source"],
        "source_sha256": digest(document),
        "code": code,
        "args": public["args"],
    }
    evidence = {
        (r["coin"], r["seconds"]): r for r in read(work / "fmz-bitfinex-575-data.json")
    }
    prehistory = {
        span: {r["coin"]: r for r in read(work / f"fmz-bitfinex-575-{span}.json")}
        for span in ("extra", "early")
    }
    jobs = []
    for coin in ("BTC", "ETH"):
        symbol = coin + "_USD"
        daily_name = f"fmz-bitfinex-{coin}-86400.json"
        daily_meta, hour_meta = (evidence[coin, seconds] for seconds in (86400, 3600))
        _, daily_raw = validated_chart(work, daily_name, daily_meta, 86400)
        hour, _ = validated_chart(
            work, f"fmz-bitfinex-{coin}-3600.json", hour_meta, 3600
        )
        joined = hour["data"]
        providers = [hour_meta]
        for span in ("early", "extra"):
            historical_meta = prehistory[span][coin]
            historical, _ = validated_chart(
                work,
                historical_meta["file"],
                historical_meta,
                3600,
                allow_sparse_before=1789430400000,
            )
            assert historical["detail"] == hour["detail"]
            assert historical["data"][-1][:2] == joined[0][:2]
            # Keep the completed version of the overlapping boundary candle.
            joined = historical["data"][:-1] + joined
            providers.insert(0, historical_meta)
        assert all(
            b[0] - a[0] == 3600000 for a, b in pairwise(joined) if b[0] >= 1789430400000
        )
        payload = json.dumps(
            {**hour, "data": joined}, separators=(",", ":"), allow_nan=False
        ).encode()
        hour_name = f"round7-bitfinex-{coin}-1h.json"
        (target / hour_name).write_bytes(payload)
        (target / daily_name).write_bytes(daily_raw)
        for start, (end, _) in WINDOWS.items():
            feed = {
                "coin": coin,
                "symbol": symbol,
                "quote_currency": "USD",
                "start": start,
                "end": end,
                "file": hour_name,
                "sha256": digest(payload),
                "providers": providers,
                "period": "1d",
                "base": "1h",
                "base_seconds": 3600,
            }
            jobs.append(
                {
                    "item": item,
                    "feed": feed,
                    "options": {
                        "opening": file_opening(target, feed, seed, IDENT),
                        "daily": {"file": daily_name, **daily_meta},
                        "fully_evaluated_exit_overlay": True,
                    },
                    "public": public,
                    "note": "Native Bitfinex daily MACD exit with ten seeded base units and 0.1 unit sales. BTC/USD preserves the archived instrument; ETH/USD is a separate port. Sample the exit logic once per hourly base bar. Retain the observed March 2026 warm-up gaps without interpolating hourly OHLCV; the research windows have consecutive observations.",
                }
            )
    original_worker = (target / "fmz_native_python_round7_worker.py").read_text(
        encoding="utf-8"
    )
    (target / WORKER).write_text(
        worker_text(original_worker), encoding="utf-8", newline="\n"
    )
    write(target / (STEM + "-jobs.json"), jobs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("--finish", type=Path)
    options = parser.parse_args()
    if options.finish:
        finish(options.target, options.finish, stem=STEM, worker=WORKER)
    else:
        stage(options.archive, options.target, options.work)
