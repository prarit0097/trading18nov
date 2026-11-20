"""Offline Pine Compat reference run for a prespecified stochastic ensemble."""

import argparse
import json
import re
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "priced-runtime"))
pine_compat = import_module("pine_compat")

FIELDS = ("time", "open", "high", "low", "close", "volume")
PLOTS = {
    1514: {
        "EMA": "ema",
        "SMA": "sma",
        "Prediction": "prediction",
        "Buy": "isNewBuySignal?1:0",
        "Sell": "isNewSellSignal?1:0",
        "Strict long exit": "endLongTradeStrict?1:0",
        "Strict short exit": "endShortTradeStrict?1:0",
        "Direction": "tradeDirection",
        "Position": "strategy.position_size",
    },
    5755: {
        "Next state": "nextState",
        "Current state": "currentState",
        "Position": "strategy.position_size",
    },
}
MODEL = "overlay=true,initial_capital=1000000,commission_type=strategy.commission.percent,commission_value=0.059)"


def seed_source(archived, ident, trial):
    base, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", archived)
    assert count == 1
    base = base.replace("overlay=true)", MODEL, 1)
    assert MODEL in base
    if ident == 1514:
        marker = "ema = ta.ema(close, emaPeriod)"
        assert base.count(marker) == 1
        equivalent = (
            "ema = 0.0\n"
            "weight = 2.0 / (emaPeriod + 1)\n"
            "ema := na(ema[1]) ? close : weight * close + (1 - weight) * ema[1]"
        )
        base = base.replace(marker, equivalent)
    site = iter(range(6))

    def seed(_match):
        return f"math.random(seed={trial * 65537 + next(site) * 8191})"

    code, count = re.subn(r"\bmath\.random\(\)", seed, base)
    assert count == (6 if ident == 5755 else 1)
    return code + "\n".join(
        f'\nplot({expr},"{title}")' for title, expr in PLOTS[ident].items()
    )


def replay(ident, trials):
    inputs = json.loads((HERE / f"r27-rng-{ident}-feeds.json").read_bytes())
    archived = (HERE / f"r27-rng-{ident}.pine").read_text(encoding="utf8")
    result = []
    for period, markets in inputs.items():
        for market, bars in markets.items():
            candles = [dict(zip(FIELDS, bar, strict=True)) for bar in bars]
            for trial in range(1, trials + 1):
                code = seed_source(archived, ident, trial)
                resolved = pine_compat.run_script(
                    code,
                    candles,
                    chart_symbol=f"BINANCE:{market}",
                    chart_timeframe="60" if ident == 5755 else "1D",
                )
                assert not resolved["diagnostics"], resolved["diagnostics"]
                broker = resolved["strategy"]
                assert not broker["diagnostics"], broker["diagnostics"]
                observations = {
                    plot["title"]: plot["values"]
                    for plot in resolved["plots"]
                    if plot.get("title") in PLOTS[ident]
                }
                assert set(observations) == set(PLOTS[ident])
                result.append(
                    {
                        "period": period,
                        "market": market,
                        "trial": trial,
                        "seeded_source_sha256": sha256(code.encode()).hexdigest(),
                        "orders": broker["orders"],
                        "trades": broker["trades"],
                        "observations": observations,
                    }
                )
    (HERE / f"r27-rng-{ident}-{trials}-receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        encoding="utf8",
        newline="\n",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ident", type=int, choices=tuple(PLOTS))
    parser.add_argument("trials", type=int, choices=(2, 32))
    args = parser.parse_args()
    try:
        replay(args.ident, args.trials)
    except Exception:
        import traceback

        (HERE / "r27-rng-probe-error.txt").write_text(
            traceback.format_exc(), encoding="utf8"
        )
        raise
