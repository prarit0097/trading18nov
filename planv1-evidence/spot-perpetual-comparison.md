## I. User-confirmed scope: Spot vs Perpetual Futures comparison

**Preference received17November2026:** user explicitly wants **dono ka comparison**. V1 therefore covers BTC/ETH spot and perpetual-futures research side by side. Exchange, quote/margin currency, jurisdiction, capital and risk limits are still unspecified. Comparison is not permission to use leverage or place orders; all execution remains shadow/paper. Unborrowed spot remains the simpler reference case, not the only product in scope.

### Product and risk comparison

| Dimension | Unborrowed spot | Perpetual futures | Required comparison rule |
|---|---|---|---|
| Position | Own BTC/ETH inventory | Derivative exposure, long or short subject to contract rules | Record product and contract identity, not just BTC symbol |
| Capital | Pay purchase notional plus fees | Post margin against notional; leverage changes collateral requirement | Report total-equity returns separately from margin ROI |
| Main recurring holding flow | No perpetual funding; custody/other charges may exist | Funding may be paid or received at eligible settlement events | Use actual event schedule and rates; no universal8h assumption |
| Price inputs | Spot trades/book | Own trades/book plus mark, index, basis and funding data | Spot candles cannot substitute for derivative fills/liquidation |
| Forced close | No margin liquidation when no borrowing | Maintenance-margin and venue liquidation rules apply | Stop-loss does not guarantee exit before liquidation |
| Fees | Account-tier spot fees/spread/impact | Account-tier derivative fees/spread/impact plus funding and modeled close/liquidation costs | Neither product assumed cheaper or zero-cost |
| Limits | Cash/inventory, venue filters | Collateral, risk tiers, position/margin modes, contract filters | Validate selected venue independently |
| Additional tail risks | Market crash, venue/custody, quote depeg | Same plus collateral loss, basis divergence, forced deleveraging/liquidation | No extra risk accepted just because expected return is higher |

Venue rules are product-specific. Binance's current USDⓈ-M documentation exposes mark/index prices, funding history and adjusted funding parameters; it does not establish this user's region/account eligibility. Bybit documents different isolated/cross/portfolio liquidation treatment and mark-price triggering, illustrating why a generic last-price candle is insufficient. These are documentation examples, not venue recommendations or account qualification. [Binance futures market-data contracts](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data), [Bybit liquidation rules](https://www.bybit.com/en/help-center/article/UTA-Trading-Rules-Liquidation-Process).

### How to compare performance fairly

1. First compare spot-long versus linear-perpetual-long at **equal notional, equivalent signals and equal initial total equity**, on overlapping periods with each product's own executable prices/costs. This separates product costs/basis from leveraged exposure. Never rank spot against a larger leveraged position by raw dollars alone.
2. Separately compare **equal pre-specified stress-loss budget**, including stop-gap, funding and margin constraints; resulting notionals may differ. Report gross/net exposure and risk alongside return. A lower collateral requirement does not increase the risk allowance automatically.
3. A perpetual long/short strategy is a third experiment. Its short opportunities change the strategy, not merely the instrument wrapper. Report the incremental short-leg results and drawdown separately.
4. Split by holding duration, funding-boundary crossings, volatility/liquidity regimes, directional market and weekend/outage conditions. Record funding cost/credit as realized only when eligible under venue rules; a favorable future funding sign is not known in advance.
5. Report net P&L, drawdown/tail loss, total-equity return, gross exposure, turnover, funding debit/credit, collateral utilization, margin calls/forced closes and rejected/partial fills. If futures risk or price history is incomplete, outcome is **not comparable/inconclusive**, not a synthetic zero-cost result.

### Funding, quantity and margin accounting

Start a futures research branch with one explicitly **linear quote-margined** BTC/ETH perpetual contract family. Inverse/coin-margined contracts require a different payoff/collateral engine and cannot reuse this formula unchanged. For linear base quantity q and position sign s=+1 long/−1 short, gross close P&L is `s*q*(exit-entry)`. At a funding event, a simplified signed cash flow is `−s*abs(q)*mark_at_settlement*rate`, **only after** validating the selected contract's quantity units, settlement eligibility, sign convention and fee currency. Round once with venue precision; journal settlements independently from fills.

For a simplified paper illustration, initial margin approximately N/L is a collateral calculation, not maximum loss or the venue's liquidation formula. The real model must include initial/maintenance requirements, tiers, close/open-order fee reserves, collateral valuation/haircuts and eligible account-mode balances. Do not estimate liquidation solely as an adverse price move of1/L; use the venue's actual rule and state. In cross mode, other positions/orders and collateral changes affect account risk. Isolated mode still needs auto-add-margin configuration and funding/fee effects modeled.

**Fictional arithmetic, not current prices/rates:** spot and linear perpetual both hold0.01BTC at100,000USDT/BTC, so each has1,000USDT notional. A1% favorable price change gives10USDT gross P&L in either instrument. At illustrative2× leverage, simplified collateral is500USDT, so10USDT looks like2% margin ROI but remains1% of a1,000USDT total account before costs. Hypothetical funding rate+0.01% on that1,000USDT notional is0.10USDT paid by a long at one eligible event under the stated sign convention. These numbers neither establish an available leverage level nor a profitable funding strategy.

### Explicit short-side sizing and nonlinear costs

Use q≥0 with a separate side flag, never negative quantity as a substitute for validated order side. For a long, stress price loss per unit is entry-buy execution minus adverse stop-sell execution; for a short it is adverse stop-buy execution minus entry-sell execution. Add entry/exit costs and conservative funding debits. Do not reduce an emergency risk reserve using speculative future funding credits. Both directions also need margin, liquidation and portfolio constraints; failure before a stop is a separate scenario, not a capped stop loss.

Depth-dependent VWAP, fees, tiers and funding exposure can depend on size. The simple risk-budget/unit-loss formula is a first bound: propose q, compute size-aware execution and margin costs, round, re-evaluate and reduce/reject until all constraints hold. A constant per-unit fee assumption cannot certify a large order's final risk. Paper tests must exercise both long and short stop gaps and reject margin-unsafe quantities even when the stop-distance bound passes.

### Free data requirements for futures branch

Alongside trade/depth data, retain historical mark/index prices, actual funding event timestamps/rates, predicted-rate snapshots with their own available-at times, current contract metadata, maintenance/risk tiers and fee schedules effective at the experiment date. Binance examples include `/fapi/v1/premiumIndex`, `/fapi/v1/fundingRate` and `/fapi/v1/fundingInfo`; the last concerns symbols with adjusted funding settings, so absence is not proof of zero funding or a complete schedule. Public documentation is not an authenticated account-tier lookup or guaranteed access. Permissioned/account data, inaccessible history and missing historical risk-tier changes must be disclosed; no paid dataset fallback is allowed.

Open interest, basis and liquidation-stream observations can be research features only after freshness/units/coverage qualification. Open interest is outstanding exposure, not traded volume. A venue liquidation feed need not expose every liquidation; do not infer complete market-wide forced selling from an unqualified public sample.

### Two separate paper-promotion gates

- **Spot gate:** cash plus fee reservation, owned-inventory exits, spot tick/step/notional filters, partial-fill protection, reconciliation and existing chronology/cost gates.
- **Perpetual gate:** all shared gates plus long/short accounting, funding sign/boundary tests, contract multipliers, separate mark/last/index clocks, tier transitions, leverage/margin/position-mode changes, collateral depeg, stop-versus-liquidation race, reduce-only/close semantics and venue forced-close accounting.
- Test that repeated funding is not charged twice after restart, no realized funding value is revealed before its historical availability, liquidation can occur before a last-price stop, and equal-notional comparison does not silently increase exposure with leverage.
- First falsify the margin engine against deterministic venue-rule fixtures. Then run historical replay, cost/funding stress and shadow/paper observation. No claim that either product has passed these gates is made in this plan.

**Decision policy:** choose neither product automatically. Compare net evidence and risk under both normal and adverse assumptions; reject a branch that needs missing data, unacceptable risk, paid access or unavailable legal/account permission. A leveraged result with higher margin ROI alone is not improved probability of profitable trading.
