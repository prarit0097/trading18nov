"""Closed-position accounting, with simultaneous settlements netted for drawdown."""

from collections import defaultdict
from math import isfinite


def metrics(rows, unsettled=0):
    totals, wins = [0.0] * 3, [0] * 3
    moves = defaultdict(lambda: [0.0] * 3)
    for timestamp, gross, fees, execution in rows:
        assert all(map(isfinite, (gross, fees, execution)))
        assert fees >= 0 and execution >= 0
        for i, value in enumerate((gross, gross - fees, gross - fees - execution)):
            totals[i] += value
            wins[i] += value > 1e-9
            moves[timestamp][i] += value
    equity, peak = [10_000.0] * 3, [10_000.0] * 3
    maximum, fraction = [0.0] * 3, [0.0] * 3
    for timestamp in sorted(moves):
        for i, change in enumerate(moves[timestamp]):
            equity[i] += change
            peak[i] = max(peak[i], equity[i])
            drop = peak[i] - equity[i]
            maximum[i] = max(maximum[i], drop)
            fraction[i] = max(fraction[i], drop / peak[i])
    return {
        "trades": len(rows),
        "unsettled": unsettled,
        "gross": totals[0],
        "after_fees": totals[1],
        "net": totals[2],
        "fees": sum(row[2] for row in rows),
        "execution": sum(row[3] for row in rows),
        "gross_wins": wins[0],
        "fee_wins": wins[1],
        "net_wins": wins[2],
        "gross_dd": maximum[0],
        "fee_dd": maximum[1],
        "net_dd": maximum[2],
        "net_dd_pct": fraction[2],
    }
