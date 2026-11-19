# BTC real-market paper test

Status: **WAIT — no current paper position or order opened.**

Latest snapshot: 2026-11-17T19:05:24.483342Z (18 November 2026, about00:35IST). Source: Binance public market-data API, BTCUSDT spot, 999 closed five-minute candles. News:30Cointelegraph RSS items, source healthy at its recorded poll time. No synthetic prices, fixture import or clock override was used.

Virtual capital:10000USDT; per-trade stop-risk budget25USDT; daily realized loss cutoff100USDT. Test order cap2000USDT and total exposure cap4000USDT. Model costs:0.1%fee per side and5bps adverse slippage; these are test assumptions, not verified account fee tiers.

Last closed candle close:63774.51000000USDT. Lagged20-bar high:64094.94000000USDT. Close did not exceed the high. Both fresh checks returned WAIT. Sizing, approval and paper submit were consequently not invoked. Rules were not loosened to manufacture a trade.

Historical backtest on this fetched window:10 closed trades, netPnL-189.7589006646USDT after modeled costs, ending cash9810.2410993354USDT. These are historical simulated fills, not a new currently opened paper order, and not evidence of a profitable strategy. Full assumptions/trades are in trader/backtest.json.

No background collector or protective exit watcher is running. No real exchange order was sent. A later qualifying market snapshot must be checked with fresh downstream risk approval before submitting a paper order.

See live-test-result.json, commands.json, trader/market.json, trader/proposal.json, trader/backtest.json and chart.svg in this run directory.
