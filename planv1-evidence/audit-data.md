# Independent data/replay/arithmetic review

Reviewed `E:/coding/code/Trade/planv1.md` on 2026-11-17 against the preserved eight-question scope, pinned TimeMachine code, inspected TradingAgents/OpenBB interfaces and the primary exchange documents recorded in `sources-data.json`. No source or final-plan edits, provider calls or trading actions performed.

## Finding requiring correction

**TimeMachine cutoff wording, plan line207:** “16:00 tak extra last candle sirf explicitly chosen horizon mein” is inaccurate. Pinned `timemachine.py:697–703` sets `until_min = end_min if until is None ...`; normal default close is16:00, and `last=(until_min-OPEN_MIN)//5-1`. Thus omitting `--until` includes the15:55–16:00 candle. Explicit `--until 15:55` excludes that candle and ends on the15:50–15:55 candle. The preceding sentence correctly states the16:00 default, so the current paragraph contradicts itself. Replace the disputed sentence with: “Explicit `--until 15:55` replays through the15:50–15:55 candle; omitting `--until` uses normal16:00 close and includes15:55–16:00.” [Pinned source](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/timemachine.py#L697).

## Checks passed and mathematical qualification

Decimal recomputation confirms the fictional example:0.01470 BTC ×1700 =24.99 USDT modeled loss; ×3800 =55.86 USDT net win;24.99/80.85 =30.9090909% break-even. Section7 raw risk quantity10/1.7 =5.8823529 units agrees with stated5.882 approximation. GitHub three repos/five-minute polling gives36 requests/hour. Spread basis points, quote notional and normalized imbalance formulas are dimensionally sound.

The expectancy equation is correct for a two-outcome sample, as the worked example explicitly says. In future implementation, “flat trades separately handled” must mean that p is conditional on non-flat trades, or use unconditional `p_win*W-p_loss*L` with flat net payoff zero. Reporting p over all trades while treating every non-win as a loss would be wrong. Current text acknowledges separate flats; this is an implementation qualification, not an additional confirmed incorrect result.

TimeMachine same-clock independent bar draws, minimum20 complete prior78-bar sessions, stop-first collision, fixed−1R gap scoring, separately simulated fan and continued underlying path all match pinned code. Ten-thousand-path evidence inflation is correctly rejected. TradingAgents graph and OpenBB historical-provider capability boundaries are accurate.

Binance archiveµs since2025-01-01 versus default WSms, closed kline flag, snapshot/update-ID resync, Coinbase300/request/no-tick omissions and Kraken720/current-uncommitted-row/checksum claims match reviewed official sources. Access eligibility is explicitly unverified. Volume/aggressor direction and wash-trade caveats are appropriately bounded.

Walk-forward chronology, purge of overlapping outcome labels, conditional embargo, single-use holdout, available-at news joins, learned-future LLM leakage, cost/fill stress and joint-asset block uncertainty are covered without treating proposed targets as measured results. All eight requested topics have dedicated sections and implementation gates. This review found no further substantive data/arithmetic correction. Performance, latency and10k-agent capacity remain unmeasured proposals; no profitability finding is established.
