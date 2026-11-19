# Independent recheck: Plan v1 after spot/perpetual scope update

Reviewed 17 November 2026. Read the eight-topic scope checkpoint, latest plan, build parts, derivative-comparison part and prior audits. This was a focused mathematical, scope, cost and liquidity review; no source code, final plan, external account, subscription or trading state was changed.

What this change does: The plan now compares BTC/ETH spot with linear quote-margined perpetuals while keeping separate accounting and promotion requirements. It proposes future research and engineering; it does not claim the collectors, matching engine, 10k-agent run or strategy have passed their gates.

## Should fix before turning formulas into evaluation code

1. **Make the expectancy denominator explicit** (`planv1.md:349`; `plan-execution.md:5`). `p` is called the out-of-sample win probability while flat outcomes are separately mentioned, but `E = p*W - (1-p)*L` is an all-trade identity only when there are no flat trades. With 40 wins of +10, 20 losses of -10 and 40 exact-zero outcomes, all-trade p=0.4 gives -2 from this expression, whereas actual mean P&L is +2. If p instead means wins conditional on a nonflat outcome, p=2/3 gives +3.333 per nonflat trade, which must be multiplied by 0.6 to obtain +2 per trade. Small fix: define `p_win`, `p_loss`, `p_flat` over the same complete denominator and use `E_all = p_win*W - p_loss*L`; alternatively define conditional p and the nonflat multiplier explicitly. The fictional two-outcome worked example is correct: quantity 0.01470, modeled loss 24.99, win 55.86 and break-even 30.9091%. This is a reporting-definition issue, not evidence the proposed strategy is unprofitable.

## Nonblocking implementation clarifications

2. **Keep the no-paid activation condition consistent** (`planv1.md:257`, C5). The social branch is said to remain disabled until a user budget/provider is configured. Read alone, this sounds like a budget can unlock a paid service. Sections A/H explicitly prohibit paid cloud inference and unknown entitlement, so the overall rule is clear. Replace that local phrase with verified zero-charge entitlement or qualified local adapter. No paid component is currently represented as available or authorized.

3. **Carry the derivative data list into the first capture milestone** (P1 versus Section I). The historical-data MVP explicitly starts with spot and P1 names generic BTC/ETH capture. Section I correctly requires separate derivative trades/book, mark/index, funding and historical rules; that requirement already exists. Explicitly reference it from P1. Otherwise an implementer following only P0-P7 could collect spot first and later discover the prospective derivative/news overlap needed for a fair comparison was never recorded. Keep retrospective data insufficiency as inconclusive; no paid repair source is permitted. This is a task-handoff risk, not a missing product branch.

## Checks that found no material defect

Equal-notional/equal-equity and equal-stress-budget comparisons are separate; short strategies are a separate experiment. Margin ROI is distinguished from total-equity return. Linear close P&L and the simplified funding sign/example are correct under their stated assumptions; inverse contracts are explicitly excluded. Actual funding schedules, mark-triggered liquidation, collateral/tier rules, venue eligibility and missing history are not hand-waved away.

Liquidity and conditional statistics are adequately bounded: touch is not guaranteed fill, aggregate L2 is not exact queue position, finite depth/partials/latency/cost stress are required, 10k simulated paths/personas are not independent observations, neither outcomes remain visible, and synthetic votes are not market probabilities. Public feeds and free software are not called costless infrastructure. All eight requested areas remain present.

Verdict: suitable as a planning deliverable after the small denominator clarification; implementation and financial qualification remain future work. No new market/provider claims required browsing in this pass. Latest live shared 300-minute quota reading at review start: 48% consumed, 52% remaining; 10% reserve preserved.

