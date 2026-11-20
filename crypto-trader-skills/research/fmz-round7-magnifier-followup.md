# Round 7 Bar Magnifier follow-up

This pass recovered the historical trade feed required for catalogue ID 5540
and checked additional public engines for the original limit-fill behavior
required by IDs 4721, 5117 and 5514.

## Binance prints reconcile with the minute candles

Binance's individual USD-M market trades reproduced all 5,760 published
minute candles across two BTC and two ETH days. The open, high, low, close,
base volume and published trade count all matched exactly. Each day also
contained trades in all 8,640 ten-second buckets. The downloaded checksum
files verified all four trade ZIPs. The archive is sufficient to construct
real ten-second OHLCV for these samples. [Binance public-data specification](https://github.com/binance/binance-public-data#futures)

| Symbol | UTC day | Individual trades | Skipped trade IDs | Minute mismatches |
| --- | --- | ---: | ---: | ---: |
| BTCUSDT | 2026-10-01 | 3,249,979 | 13,102 | 0 |
| BTCUSDT | 2026-11-01 | 1,190,743 | 6,607 | 0 |
| ETHUSDT | 2026-10-01 | 4,072,249 | 13,187 | 0 |
| ETHUSDT | 2026-11-01 | 1,580,258 | 7,369 | 0 |

Reproduce the check with Binance USD-M daily trades and klines ZIPs for the
symbol and day, plus the corresponding checksum files. Stream individual
trades in archive order and assert strictly increasing ID and nondecreasing
millisecond timestamp. Bucket by UTC minute and compare first price,
maximum, minimum, last price, exact decimal quantity sum and count with the
published kline. Separately count the occupied ten-second bins. An ID skip
is tracked independently of missing market prints. Binance documents that
this public trade surface omits insurance-fund and ADL trades. The exact
kline trade-count matches establish the coverage of the published
market-trade series for these four days. [Binance USD-M market-data API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#recent-trades-list)

ID 5540 still requires account-currency conversion during strategy execution.
The archived source sizes each entry from strategy.equity under a USD account
on a USDT-quoted contract. TradingView specifies that conversion is based on
the previous daily exchange rate and applies during the strategy's
calculations. Piner 0.13.0 ignored the account currency in the first audit's
USD/EUR fixture. A fixed one-to-one price ratio or conversion of the output
ledger would leave prospective position sizing unverified.
[TradingView currency semantics](https://www.tradingview.com/pine-script-docs/concepts/strategies/#currency) · [Round 7 initial replay](fmz-round7-magnifier.md)

## Archived one-tick limit verification

TradingView requires the market path to move a specified number of ticks
past a qualifying limit while preserving the order's fill price. Piner 0.13.0,
the latest registry version at the audit, implements at-touch logic in
its entry, stop-limit and bracket paths. The isolated watch-only probe
observed the unchanged ID 4721 strategy over the two existing BTC and ETH
45-minute to five-minute windows. The plain JavaScript engine, observed
JavaScript engine and observed interpreter produced identical complete
reports and 92 closed trades. None exercised the limit-close branch.
[TradingView limit verification](https://www.tradingview.com/pine-script-docs/concepts/strategies/#slippage-and-unfilled-limits) · [Piner release package](https://www.npmjs.com/package/@heyphat/piner/v/0.13.0)

The PineForge code generator exposes the threshold in capability metadata.
The checked runner explicitly refuses nonzero values and the generic
fill-through order is a market-if-touched rule. PyneCore records the parameter
at declaration with no downstream broker use. PineTS supports verification
but its prior historical engine audit did not validate an active
lower-timeframe magnifier. These checks establish the limits of those paths
for the archived programs.
[PineForge runner guard](https://github.com/pineforge-4pass/pineforge-engine/blob/665fc4ddc024951dd1c911ad5de9839a5c91e2e4/runner/capabilities.hpp#L143-L148) · [PineForge generic matching](https://github.com/pineforge-4pass/pineforge-engine/blob/665fc4ddc024951dd1c911ad5de9839a5c91e2e4/docs/pages/pine-to-native.md#order-lifecycle) · [PyneCore declaration](https://github.com/pynesys/pynecore/blob/09238ba8d2d4649a0764d94970968b8afdcadc41/src/pynecore/core/script.py#L691) · [Round 6 PineTS audit](remaining-backtests-round6.md)
