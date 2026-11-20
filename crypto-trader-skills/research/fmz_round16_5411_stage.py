"""Prepare #5411 fully closed Binance candles under a fixed archived UTC clock."""

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import raw_ohlcv, sha256, verified_archives, write

RAW_DIGESTS = {
    "5411-BTCUSDT-2019-2023.json": "4b84cdfc2754a978db2e2847f31d9f590407867d4e20b456c4f60d596fb48eda",
    "5411-BTCUSDT-2024.json": "f7be254ae6afc14944a1f52f06356f62931b27e8141e31734209d7befeeb5993",
    "5411-ETHUSDT-2019-2023.json": "1c6fa220e4044c6122582b0b91290109053d29bf50a47f4c7c216ada1eb78bf7",
    "5411-ETHUSDT-2024.json": "4d3dfa3f18951a2963aef4c2b597fb25f17406c052f8ac39d44671ac1cd3af3d",
}

DAY = 86_400_000


def moment(year, month, day, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp()) * 1000


def stage(raw_root, market_check, work):
    start = moment(2019, 12, 23, 8)
    clock = moment(2024, 12, 9, 8)
    gate = moment(2024, 11, 9)
    assert (clock // DAY - 30) * DAY == gate
    first_day = moment(2019, 12, 23)
    final_open = moment(2024, 12, 9)
    record = {
        "start": start,
        "clock": clock,
        "gate": gate,
        "history": [],
        "gate_crosschecks": [],
    }
    for market in ("BTCUSDT", "ETHUSDT"):
        windows = (
            ("2019-2023", first_day, moment(2024, 1, 1)),
            ("2024", moment(2024, 1, 1), clock),
        )
        candles = []
        sources = []
        for label, cursor, stop in windows:
            path = raw_root / f"5411-{market}-{label}.json"
            digest = sha256(path)
            assert digest == RAW_DIGESTS[path.name]
            payload = json.loads(path.read_bytes())
            assert [row[0] for row in payload] == list(range(cursor, stop, DAY))
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={market}&interval=1d&startTime={cursor}&endTime={stop - 1}&limit=1500"
            for row in payload:
                assert len(row) == 12 and row[6] == row[0] + DAY - 1
                o, h, l, c, v = map(Decimal, row[1:6])
                assert 0 < l <= min(o, c) <= max(o, c) <= h and v > 0
                if start <= row[0] and row[6] < clock:
                    candles.append([row[0], *map(float, (o, h, l, c, v))])
            sources.append(
                {"file": path.name, "url": url, "sha256": digest, "rows": len(payload)}
            )
        assert [row[0] for row in candles] == list(
            range(first_day + DAY, final_open, DAY)
        )
        archives = verified_archives(
            market_check,
            market,
            "1d",
            ("2024-11", "2024-12"),
            record["gate_crosschecks"],
        )
        source_prices = {row[0]: row for row in candles if gate <= row[0]}
        public_checks = 0
        for archive in archives:
            for bar in raw_ohlcv(archive, DAY):
                if gate <= bar[0] < final_open:
                    assert source_prices[bar[0]] == list(bar)
                    public_checks += 1
        assert public_checks == len(source_prices) == 30
        output = work / f"5411-feed-{market}.json"
        output.write_bytes(
            json.dumps(candles, separators=(",", ":"), allow_nan=False).encode()
        )
        record["history"].append(
            {
                "symbol": market,
                "file": output.name,
                "sha256": sha256(output),
                "bars": len(candles),
                "sources": sources,
                "eligible_archive_checks": public_checks,
            }
        )
    write(work / "5411-inputs.json", record)


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
