# Trade 1 pause and diagnosis handoff

## Verified campaign checkpoint

The owner paused Trade 1 on 19 November 2026. The local entry hold took effect at 19:29:30 IST. The entry journal records 0 new submissions after that point. The last ETH position closed at 19:36:22 IST for −$0.00819768 after fees and funding. The signed Delta India testnet account check was flat with zero open or pending exchange orders.

The checkpoint contains **209 verified three-contract closes**, **20 finalized ten-trade reviews** and **9 verified members of Review 21**. The observer remains live under the entry hold. The registered prospective capture is read-only.

## Baseline evidence

| Measure | Value |
| --- | ---: |
| Net wins | 49 / 209 (23.4%) |
| Gross winners | 91 / 209 (43.5%) |
| Gross winners that finished at zero or a loss after costs | 42 |
| Realized gross P&L | −$2.06400000 |
| Commissions paid | $21.80788456 |
| Signed funding | −$0.02931362 |
| Realized net P&L | **−$23.90119818** |
| Average net P&L | −$0.11435980 |
| Average net winner | +$0.13581845 |
| Average net loser | −$0.19097689 |
| Break-even win rate at these observed payoffs | 58.4% |
| Source baskets and IST settlement days | 65 baskets, 1 day |

Net P&L is the recorded gross P&L minus commissions plus signed funding. Gross P&L uses realized fill prices, so spread and slippage may already affect it. All 209 closes used the same recorded baseline version. Coin and signal rows show descriptive differences in this sample. Related positions in one basket share market exposure, and the one-day sample cannot measure performance across market regimes.

| Coin | Closed | Net wins | Gross USD | Fees USD | Net USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTCUSD | 47 | 10 | +$0.47700000 | $9.46565774 | −$9.00777731 |
| DOGEUSD | 5 | 0 | −$0.17700000 | $0.09491576 | −$0.27077979 |
| ETHUSD | 61 | 16 | +$0.75450000 | $3.47325621 | −$2.72950059 |
| SOLUSD | 36 | 8 | −$3.03000000 | $8.58780909 | −$11.61780909 |
| XRPUSD | 60 | 15 | −$0.08850000 | $0.18624576 | −$0.27533140 |

| Entry signal | Closed | Net wins | Gross USD | Fees USD | Net USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| READY | 15 | 1 | −$2.42400000 | $1.71872455 | −$4.14272455 |
| Unavailable | 1 | 0 | −$0.75600000 | $0.23628970 | −$0.99228970 |
| WAIT | 193 | 48 | +$1.11600000 | $19.85287031 | −$18.76618393 |

## Duration and execution evidence

The first 200 verified closes supplied 125 official 15-minute comparisons with a mean change of −$0.05068537, and 95 official 30-minute comparisons with a mean change of −$0.04468884. Trades 205–208 supplied 4 additional 15-minute displayed-depth matches, with +$0.31553456 actual net versus +$0.80259279 modeled net. This later basket is a useful sensitivity case alongside the earlier comparisons.

For trades 201–204, public funding observations supported three 30-minute pairs. Actual net was −$0.09415667 and modeled net was +$0.76022516 on those three entries. DOGE remained unavailable because its modeled window crossed a scheduled funding settlement. The replay used 242 frozen funding observations and reproduced offline.

The first pre-intent order-book test observed four full fills in one basket. The public depth rule and both baselines each matched all four, and the basket realized −$0.13113568 after costs. Test collection and exchange timestamps use different clocks. Use venue-to-venue intervals for exchange timing and comparable local receipts for pre-intent feature selection.

For the last ETH trade, the 15-minute reference is verified at −$0.05484015 modeled against −$0.00819768 realized. The 30-minute reference becomes eligible at 19:57 IST on 19 November. The public 30-minute replay for trades 205–208 also depends on funding evidence through its own deadline. Estimated P&L remains outside realized trade totals. Review 21 requires one more verified trade in a future authorized run.

## Data sources

- [Verified workbook snapshot](outputs/01a1df70-6789-76b0-9431-f0c905a7987a/trade1.xlsx) contains the campaign overview, executed positions, review records and paired duration observations.
- [Review evidence](runs/trade1/reviews.json) contains exact ten-trade membership, evidence digests, specialist findings and decisions. Join trade rows by exchange entry order ID.
- [Paired duration data](runs/trade1/shadows.json) records actual net P&L, modeled outcomes and unavailable reasons by trade ID. Keep horizon and evidence status when joining rows.
- [Pre-intent IOC observation](runs/trade1/ioc-pre-intent-observation-20261119.json) contains the frozen selection, signed quantity scores and later realized costs for its own sample.
- [Frozen candidate protocol](runs/trade1/research-ready-pilot.md) documents the four-READY study and modeled execution assumptions. The frozen 84-day window begins on 20 November 2026 at 00:00 IST.
- The local execution journal and local ledger under runs/trade1 provide matched order attempts, fill and wallet evidence for detailed analysis. Credentials and private account rows stay local.

## Analysis order

1. Freeze this cohort and reproduce gross, fee, funding and net totals from the workbook and local settlement records. Count exactly three settled contracts per position. Preserve zero-filled and guarded attempts in execution analysis.
2. Explain the difference between gross and net wins by coin, signal, spread and local market time. Quantify which gross winners disappear after fees. With a valid pre-intent quote or venue book, estimate entry and exit execution effects as a sensitivity. Keep unavailable benchmarks visible.
3. Compare READY and WAIT in matched coin and market conditions. Compare durations on the same positions and show the number of matched, pending and unavailable references. Evaluate both net win frequency and average after-cost P&L.
4. Use basket and day as dependence units. Use additional days of passive data to qualify a candidate. Require positive after-cost expectancy, improvement over baseline in both win probability and mean net P&L, cost-stress stability and compliance with existing drawdown and risk limits.

The current decision is to keep new demo entries on hold during diagnosis. A later owner resume instruction is required to reopen entries.
