# planv1.md — crypto research scope checkpoint

## Status

Completed on17November2026: detailed planv1.md created and cross-verified. Validation: planv1-evidence/validation.json; independent reviews: planv1-evidence/cross-review.md. The earlier pause occurred at97%consumed/3%remaining; work resumed after a verified reset. Plan delivery does not mean the proposed crypto system has been implemented or shown profitable.

## User requirements

All future trading analysis is for cryptocurrency, including Bitcoin/BTC and Ethereum/ETH. No paid subscriptions. Goal: investigate how to improve the probability of profitable trading, without inventing evidence or guaranteeing returns.

1. Inspect Markdown reports in E:\coding\code\Trade and backing repository source: how news is fetched, source websites, actual freshness/polling cadence, correctness and bottlenecks. Compare free alternatives and design lowest-practical-latency news delivery. Distinguish publish time, discovery time, transport time and notification latency; do not promise globally first delivery on free feeds.
2. Trace existing backtesting and propose suitable crypto validation methodology.
3. Trace historical-market-data/chart ingestion and reading; compare better free crypto-specific options.
4. Explain day-trader Time Machine implementation and improve order/strategy/entry/exit testing. Separate stochastic scenarios, historical replay, execution simulation and predictions.
5. Assess MiroFish for trade/task/order simulations with10000+ agents. Distinguish synthetic correlated personas from10000 real independent market participants, measured capacity from README claims, and monetary/token cost from free software licensing.
6. Trace volume measurement and improve crypto market-volume/liquidity/order-flow handling.
7. Propose risk management appropriate to crypto markets and the user's unpaid-data constraint.
8. Trace data→entry→exit plan→sizing→risk and propose a stronger integrated workflow.

## Deliverable and verification

- Write E:\coding\code\Trade\planv1.md with detailed practical architecture, approaches/tradeoffs, source-backed current behavior, clearly labeled proposals, dependencies/limits, validation criteria and implementation phases.
- Browse current authoritative primary documentation for free APIs/WebSockets/RSS/news access, latency/update semantics, rate limits, retention and terms; no guessed current quotas or unsupported recommendations.
- Cross-verify plan against repo source and evidence, distinguish measured results from assumptions and untested ideas, validate citations/local links/coverage of all8 points.
- User explicitly permits agent-team delegation if needed; respect shared quota reserve and use focused domains.
- Do not modify source repos, place broker/exchange orders, purchase subscriptions, use paid inference or treat Paperclip/MiroFish forecasts as verified trading edge.

## Existing context

Reports: daytrade.md, obb.md, tradingagent.md. Requested mirofish.md currently contains Paperclip analysis; original MiroFish report is paperclip-evidence/mirofish-original-report.md. Backing source/evidence folders for all five repos exist. RUNTIME-TEST-CHECKPOINT.md records separate unfinished Paperclip runtime qualification and previous fresh results; do not confuse that older task with this new plan request.

## Completion and future execution

The requested planning task is complete. Original requirements above are preserved. Implementation remains unchecked tasksP0–P7 in planv1.md, with user-confirmed BTC/ETH spot-versus-perpetual comparison and separate paper-promotion gates. Exchange/leverage/margin settings remain unspecified; no live trading authorization. Runtime-test work for Paperclip is a separate older checkpoint, not a prerequisite falsely claimed complete here. Any new execution must again respect the owner quota reserve and explicit trading/provider permissions.
