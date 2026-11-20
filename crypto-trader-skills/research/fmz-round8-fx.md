# Round 8 FMZ USD-account replay

Catalogue ID 5540 ran on four independent historical samples of Binance
USD-M perpetuals. The archived one-minute Pine program consumed six
ten-second candles per minute. On 2026-10-01 and 2026-11-01 UTC, the BTCUSDT
runs produced 9 and 19 closed lots and the ETHUSDT runs produced 8 and 9.
The two dates were selected during the Round 7 data-quality investigation.
Each replay used the archived $20,000 initial capital and 0.075%
commission per side. [Archived FMZ source](https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E9%80%9A%E7%94%A8%E5%9B%9E%E6%B5%8B%E7%AD%96%E7%95%A5%E6%A8%A1%E6%9D%BFUniversal-Strategy-Backtest-Template.md) · [Round 7 input checks](fmz-round7-magnifier-followup.md)

Position sizing reads the replay broker's native USD equity. The public
Coinbase Exchange USDT-USD close from the previous complete UTC day becomes
effective at the next UTC midnight. The applied rates were 0.99935 USD
per USDT on October 1 and 0.99878 on November 1. This explicitly selects
Coinbase as the conversion source for this replay. The default source
selection of TradingView currency conversion can differ.
[Coinbase daily candle API](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles) · [TradingView strategy currency](https://www.tradingview.com/pine-script-docs/concepts/strategies/#currency)

The original program, with only the FMZ host wrapper removed, runs in
Pine Compat Runtime 0.3.3 inside the offline Python AppContainer harness.
The replay uses a 0.1 USDT tick for BTCUSDT, a 0.01 USDT tick for ETHUSDT,
and a 0.001 base-asset lot step for both. Six results cover BTC, ETH and pooled independently funded
accounts for each date. For every closed lot the report independently
reconstructs gross USD P&L, both fees and net USD P&L from the broker fills.
It reports remaining exposure separately and computes drawdown from the
closed-trade equity series. Funding is outside this broker replay model.
[Pine Compat Runtime 0.3.3 release](https://github.com/helenananaa/pine-compat-runtime/releases/tag/v0.3.3) · [Result and input checksums](fmz-round8-fx.json)

The two public runtime entry points returned equal results. Missing
magnifier coverage generated a fallback diagnostic in a control. All four
complete samples produced zero such diagnostics and every minute rolling
up the ten-second candles matched Binance's minute OHLCV and trade count.
The original strategy sends a disabled profit leg as NA while flat. A
separate control gated those calls on the open position and returned the
same order, position, trade and equity output. Metrics are derived from
the unmodified archived program. The runtime exposes fill timestamps at
the one-minute chart resolution.

## Reproduction

Use the data ZIPs and checksum files specified in the Round 7 evidence.
The five staging payloads consist of four market/day feeds and the Coinbase
FX input envelope. The replay checks the pinned bytes of the archived Pine
source and the wheel's loaded native binary.

```powershell
python -m research.fmz_round8_fx stage Scratch RawTrades PublicKlines CoinbaseDaily.json
Copy-Item research/fmz_round8_fx_runner.py Scratch/runner.py
Scratch/sandbox.ps1 Scratch runner.py '' 150
python -m research.fmz_round8_fx finalize Scratch research/fmz-round8-fx.json
```

Place the archived source-5540.pine in Scratch using the Round 7 source
prep. Install the published, checksum-verified 0.3.3 Windows wheel into
Scratch for the offline isolated Python runner. Use the same AppContainer
Python launcher and isolation probe as the earlier FMZ native Python runs.
