"""Retry pinned Freqtrade strategies with explicit, audited compatibility changes."""

import hashlib
import json
import logging
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import nonpine_freqtrade as base


REPAIRS = {
    5813: "5m demonstration interval. Replace removed forward-fill lookup with sorted timestamp search and check for no historical row.",
    5814: "Remove unused NumPy math import. Restore candles excluded by pretrained feature cleanup with missing features.",
    5815: "Restore candles excluded by the original pre-indicator filter with missing features. Preserve original cleanup and shifted indicators.",
    5830: "Route the explicitly named BTC/USDT:USDT informative series to Binance perpetual candles while preserving spot trading.",
    5863: "Remove unused NumPy math import.",
    5864: "Declare parameter spaces for the source ADX and EMA periods while preserving their defaults.",
    5875: "Remove unused pandas_ta import and load the source-defined ETH/BTC spot informative route.",
}


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def repair(ident, path):
    code = path.read_text(encoding="utf-8-sig")
    if ident == 5813:
        return once(
            code,
            "open_date_mask = custom_info_pair.index.unique().get_loc(trade.open_date_utc, method='ffill')",
            "open_date_mask = custom_info_pair.index.searchsorted(trade.open_date_utc, side='right') - 1\n"
            "            if open_date_mask == -1:\n                return -1.0",
        )
    if ident in (5814, 5863):
        code = once(code, "from numpy.lib import math\n", "")
    if ident in (5814, 5815):
        code = once(
            code,
            "        dataframe = dropna(dataframe)",
            "        observed = dataframe.copy()\n        dataframe = dropna(dataframe)",
        )
        start = code.index("    def populate_indicators(")
        end = code.index("    def populate_entry_trend(", start)
        section = once(
            code[start:end],
            "return dataframe",
            "return observed.join(dataframe.drop(columns=observed.columns), how='left')",
        )
        code = code[:start] + section + code[end:]
    if ident == 5830:
        for interval in ("1h", "4h"):
            code = once(
                code,
                f'("BTC/USDT:USDT", "{interval}")',
                f'("BTC/USDT:USDT", "{interval}", "futures")',
            )
        code = once(
            code,
            "pair='BTC/USDT:USDT', timeframe='1h'",
            "pair='BTC/USDT:USDT', timeframe='1h', candle_type='futures'",
        )
    if ident == 5864:
        code = once(
            code,
            "IntParameter(4, 24, default=14)",
            'IntParameter(4, 24, default=14, space="sell")',
        )
        code = once(
            code,
            "IntParameter(4, 24, default=8)",
            'IntParameter(4, 24, default=8, space="buy")',
        )
        code = once(
            code,
            "IntParameter(12, 175, default=21)",
            'IntParameter(12, 175, default=21, space="buy")',
        )
    if ident == 5875:
        code = once(code, "import pandas_ta as pta\n", "")
    return code


def informative_ethbtc():
    market_dir = ROOT / "binance" / "ethbtc"
    manifest = json.loads((market_dir / "manifest.json").read_bytes())
    for file, _, digest in manifest:
        assert hashlib.sha256((market_dir / file).read_bytes()).hexdigest() == digest, (
            file
        )
    original = base.CANDLES
    try:
        base.CANDLES = market_dir
        candles = base.parse_candles("ETHBTC-1h-*.zip", 60)
        assert (candles.volume > 0).all()
        adapter = base.get_datahandler(base.DATADIR, "feather")
        adapter.ohlcv_store("ETH/BTC", "1h", candles, base.CandleType.SPOT)
    finally:
        base.CANDLES = original


class ReplayGuard(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.issue = None

    def emit(self, record):
        message = record.getMessage()
        if (
            "Unexpected error" in message
            or "No data found for" in message
            or "No history for" in message
        ):
            self.issue = message.splitlines()[0]


def main():
    warnings.filterwarnings("ignore")
    root_logger = logging.getLogger()
    logging.basicConfig(
        filename=ROOT / "freq-round2.log", level=logging.WARNING, encoding="utf-8"
    )
    guard = ReplayGuard()
    root_logger.addHandler(guard)
    stock = base.read(ROOT / "freq-catalogue.json")
    if len(sys.argv) > 1:
        ids = set(map(int, sys.argv[1:]))
        assert ids <= REPAIRS.keys()
    else:
        ids = REPAIRS.keys()
    if 5875 in ids:
        informative_ethbtc()
    suffix = "-" + sys.argv[1] if len(sys.argv) > 1 else ""
    with (ROOT / f"freq-round2{suffix}-out.jsonl").open("w", encoding="utf-8") as out:
        for item, name, mode, digest in base.candidate_sources(
            [x for x in stock if x["id"] in ids]
        ):
            ident = item["id"]
            guard.issue = None
            try:
                [path] = (ROOT / "freqsrc" / str(ident)).glob("*.py")
                changed = repair(ident, path)
                path.write_text(changed, encoding="utf-8", newline="\n")
                rows = [
                    row
                    for period, dates in base.WINDOWS.items()
                    for row in base.analyze(item, name, mode, digest, period, dates)
                ]
                if guard.issue:
                    raise ValueError(guard.issue)
                for row in rows:
                    row.update(
                        group="Freqtrade compatibility replay · Binance",
                        source_adaptation=REPAIRS[ident],
                        migrated_sha256=hashlib.sha256(changed.encode()).hexdigest(),
                    )
                record = dict(id=ident, results=rows)
            except Exception as exc:
                logging.exception("Rejected %d", ident)
                record = dict(
                    id=ident,
                    reason=f"{type(exc).__name__}: {exc}".splitlines()[0].replace(
                        str(ROOT), "scratch"
                    ),
                )
            out.write(json.dumps(record, allow_nan=False) + "\n")
            out.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        (ROOT / "freq-round2-failure.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise
