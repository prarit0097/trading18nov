# Plan v1 independent cross-review

Reviewed 17 November 2026. Subject: planv1.md, crypto-only eight-point request, no paid subscriptions.

- Data/methodology reviewer: all eight topics present; arithmetic, timestamp units, Monte Carlo limits, volume and chronology checked. Found one incorrect sentence suggesting16:00 final candle needed explicit horizon. Corrected in data-notes.md and rebuilt plan: omitted --until defaults16:00; explicit15:55 stops one candle earlier. Original review retained in audit-data.md.
- Independent risk/simulation reviewer: no material contradiction found in free-source eligibility/cost boundaries, versioned/atomic risk proposal, exit protection, unknown-order reconciliation or10k-agent limits. Future tasks remain unchecked; numerical targets are not measured performance. Original review retained in audit-risk.md.
- Root cross-check: official CFTC disabled-feed notice, Binance announcement credentials and Alpha Vantage premium endpoint marking re-read independently. Global no-paid rule clarified for optional components as well; crypto asset gate excludes company fundamentals/NYSE assumptions. No source repository behavior was altered.

Mechanical checks and arithmetic are recorded in validation.json. These checks are document/source consistency, not evidence that proposed future collectors, matching simulator or BTC/ETH strategy work or earn profits. Explicitly untested: fastest publication-to-phone latency, exchange/account eligibility,10k-agent capacity, new strategy out-of-sample returns, paid/live providers and real orders.

## Preference update: spot and perpetual comparison

User later explicitly selected comparison of both products. Updated scope, roadmap, risk notes and newSectionI accordingly. Original independent reviews above concern the preceding eight-topic draft; newSectionI was root-reviewed against current Binance futures market-data documentation and Bybit liquidation rules. Decimal checks verify equal-notional example, simplified marginROI versus total-equity return, and hypothetical funding. No new derivative engine, account eligibility, live price/rate or leverage setting was tested. Both branches remain paper-only and separately gated.

## Detailed recheck after user authorization

Independent review: [recheck-review.md](recheck-review.md). Findings were applied to builder inputs and rebuilt into the same planv1.md, not patched only in the generated output.

Corrections:
- Explicit unconditional win/loss/zero-net probabilities, conditional nonflat expectancy and timeout settlement; Decimal example9.849 verified.
- Canonical internal latency target p95≤250ms/p99≤2s; publisher age is a diagnostic, not a guaranteed SLA.
- Per-fill transfer/fee reconciliation separated from changing mark-to-market equity.
- P1 captures both spot and linear-perpetual data plus mark/index/funding early.
- Social simulation cannot activate paid calls merely from a provider/budget setting.
- Short-side sizing and size-dependent VWAP/margin/cost recheck requirements added.
- Stray leading patch markers removed from20 input lines, restoring F and other heading/paragraph rendering.

Fresh validate-plan.py passes source ranges, tables/fences, navigation, requirements/tasks, original and new arithmetic, product comparison and regression checks; tracked diffs in all5 source repositories remain empty. This is plan/document validation, not a new trading benchmark or certification of profitable execution.
