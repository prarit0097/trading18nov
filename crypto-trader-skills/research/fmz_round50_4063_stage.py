"""Prepare the archived daily chart and complete calendar-quarter context."""
from itertools import groupby
from pathlib import Path
import sys

from research.fmz_round7_magnifier import date_ms, verified_archives, write
from research.fmz_round26_977 import prices
from research.fmz_round50_4063 import DAY, quarter


def stage(caches, out):
    months = [f'{year}-{month:02d}' for year, lo, hi in ((2022, 4, 12), (2023, 1, 12))
              for month in range(lo, hi+1)]
    markets, receipts = {}, []
    start, end = map(date_ms, ('2022-11-14', '2023-11-20'))
    for symbol in ('BTCUSDT', 'ETHUSDT'):
        files = []
        for month in months:
            name = f'{symbol}-1d-{month}.zip'
            home = next(directory for directory in caches if (directory/name).is_file())
            files.extend(verified_archives(home, symbol, '1d', (month,), receipts))
        daily = prices(files, date_ms('2022-04-01'), date_ms('2024-01-01'), DAY)
        quarters = []
        for _, group in groupby(daily, key=lambda row: quarter(row[0])):
            period = list(group)
            quarters.append([period[0][0], period[0][1], max(r[2] for r in period),
                             min(r[3] for r in period), period[-1][4], sum(r[5] for r in period)])
        chart = [r for r in daily if start <= r[0] < end]
        markets[symbol] = {'chart': chart, 'daily': daily, 'quarter': quarters}
    write(out, {'markets': markets, 'receipts': receipts})


if __name__ == '__main__':
    paths = list(map(Path, sys.argv[1:]))
    stage(paths[:-1], paths[-1])
