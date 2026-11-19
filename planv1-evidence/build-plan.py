from pathlib import Path
import json,re
b=Path(r'E:\coding\code\Trade');e=b/'planv1-evidence'
def read(name):return (e/name).read_text(encoding='utf-8')
def sections(name):
 s=read(name);out={}
 for piece in re.split(r'(?m)^## ',s)[1:]:
  title,_,body=piece.partition('\n');num=re.match(r'(\d+)\.',title)
  if num:out[int(num[1])]=(title,body.strip())
 return out
n=sections('news-notes.md');d=sections('data-notes.md');s=sections('sim-risk-notes.md')
def chunks(items):
 return '\n\n'.join('### '+t+'\n\n'+body for t,body in items)
# Contributor-local bookkeeping is not part of the reader-facing plan.
def clean(text):
 text=text.replace('Requested `Paperclip-in-mirofish.md` filename this checkout mein nahi mila; substitute silently pretend nahi kiya. ','')
 text=re.sub(r'Usage reserve remains independent:.*?remaining\.','',text,flags=re.S)
 text=text.replace('Existing NVDA evidence `nvda-timemachine/20261116T153319Z/RESULT.md` historical triggered-trade replay label karta hai: 57 prior full sessions, explicit 15:55 horizon, 10,000 generated paths; current live signal waiting tha. Monte Carlo mean −0.102R aur historical rule mean −0.258R reported hain. Yeh captured run ka result hai, BTC/ETH evidence ya positive strategy edge nahin. Source data hash, exact commands aur verification companion files mein retained hain.','Existing captured equity replay verified the software path, not BTC/ETH performance. No crypto edge is inferred from that earlier run.')
 return text
parts=[read('plan-core.md')]
groups=[
 ('1. News: source, freshness, free access aur fastest practical delivery',chunks([n[i]for i in sorted(n)])),
 ('2. Backtesting: implemented capability aur cost-aware validation',chunks([d[1],d[5]])+'\n\nCandle-screening baseline ko conditional prototype maanein. Freqtrade documents requested-price/range-based assumptions; no-slippage backtest is insufficient for news-sensitive fast trading. Its lookahead check can miss untriggered branches. Event execution study should configure finite liquidity, queue assumptions and actual costs explicitly rather than accept any simulator default. [Backtest assumptions](https://www.freqtrade.io/en/stable/backtesting/), [diagnostic scope](https://www.freqtrade.io/en/latest/lookahead-analysis/), [fill-model controls](https://nautilustrader.io/docs/latest/concepts/backtesting/fill-models/).'),
 ('3. Historical data aur charts: venue truth, units, gaps and replay',chunks([d[3],d[4]])),
 ('4. Time Machine: exact method aur crypto replacement',chunks([d[2]])+'\n\n**Replacement decision:** one experiment mode historical event replay, second joint contiguous-block bootstrap, third regime/fault stress. Horizon crypto holding rule se explicit ho, US market close se nahi. Har output mein target-first/stop-first/neither counts, settled net P&L, conditional vs unconditional probability and historical-pool size show hon. Seed reproducibility numerical stability hai, real-world prediction accuracy nahi. Exact same strategy/volume/stop rules ko replay and paper mode mein share karna mandatory contract ho.'),
 ('5. MiroFish aur10,000+ agents: what can actually be tested',chunks([s[1],s[2],s[3]])),
 ('6. Volume: measurement, liquidity and validation',chunks([d[6]])+'''\n\n### Proposed feature definitions (not validated alpha)

- `quote_notional = sum(trade_price * base_quantity)`, not bar-close times volume when exact trade data exists. `RVOL = current_closed_bar_volume / median(past comparable closed-bar volumes)`; comparable UTC/weekday buckets and finite lookback chosen on training data only. Missing coverage/zero denominator returns invalid, not an invented signal.
- `spread_bps = 10000*(best_ask-best_bid)/mid`. For buy quantity q, executable ask-side VWAP walks finite depth; insufficient depth rejects or partially fills per declared rule. More reported24h volume doesn't imply enough size at the current spread.
- `OBI = (bid_notional - ask_notional)/(bid_notional + ask_notional)` over the same declared depth/radius. Cancelable displayed liquidity is not guaranteed fill liquidity. Record the measurement window and depth limit.
- Signed trade imbalance/CVD uses documented aggressor semantics. On Binance buyer-is-maker=true means buyer passive, so the trade is sell-initiated; don't reverse this flag. These measure aggression, not identifiable investor inflows or guaranteed future direction.
- BTC/USDT spot, BTC/USD spot and BTC perpetual contracts have different units/fees/venues. Never add raw token counts across them or call unrelated venue volume executable on the chosen venue. Mark conversions at their available-at time.
'''),
 ('7. Risk management: crypto capital, execution and operational controls',chunks([s[5]])+'''\n\n### Operational risk additions, proposed

Keep independent limits for per-trade modeled loss, rolling24h realized plus marked loss, gross exposure, BTC/ETH factor concentration, open-order reservations, venue/quote-currency concentration and strategy drawdown. These are configurable research constraints, not validated personal allocation percentages. Balance/token depeg, exchange outage/custody, precision, bad feed and compromised source/key scenarios belong in stress tests. No withdrawal permission is needed for paper research; any future real executor needs separately scoped credentials and explicit user authorization.

Stale feed prevents new entries; protective order monitoring/reconciliation must keep running. A stop's trigger is not guaranteed execution. The response to unknown order state is reconcile by client/venue ID before retry, never blindly duplicate. If native reduce-only/OCO/brackets are absent for selected spot order types, local orchestration must enforce inventory reservations and address its own outage risk. Any fallback remains unqualified until tested on that venue.
'''),
 ('8. Data → entry → exit plan → sizing → risk: integrated replacement',chunks([s[4],s[6]])+'''\n\n### Proposed decision-to-fill contract

1. Read a healthy, versioned, point-in-time market/news snapshot. Input freshness and source truth are separate flags.
2. Evaluate the fixed strategy only at its declared decision boundary; reject expired signals and incomplete required history. A chosen24/7 session anchor is explicit and tested, not “NYSE open” accidentally copied.
3. Build entry/stop/target/horizon and expected order type. Compute required reward after costs; if spread/fees erase plausible payoff or the stop is not executable under assumptions, reject the proposal.
4. Size from stress loss and free/reserved cash, then round with current venue filters and re-check all caps. Cash needed for entry fees and multiple pending orders counts.
5. Atomically reserve cash/inventory/risk and issue versioned short-lived RiskDecision. Validate it again at paper-send time; changed portfolio, market sequence, policy or metadata invalidates it.
6. Execute through paper/shadow adapter, apply latency/fill/reject/partial/cancel rules and journal each transition. No same-close magical fill after seeing the candle.
7. Reconcile positions/orders/fees, resize protective quantities after partial fills, and update actual risk. Record planned versus actual stop price and measured versus realized loss separately.
8. Evaluate OOS net outcomes and safety violations; neither LLM confidence nor a Paperclip approval can bypass deterministic risk gates.
''')]
anchors=['news','backtesting','historical-data','time-machine','agent-simulation','volume','risk','trade-pipeline']
toc='## Eight-point navigation\n\n'+ '\n'.join(f'- [{i+1}. {title.split(". ",1)[1]}](#{anchor})' for i,((title,_),anchor) in enumerate(zip(groups,anchors)))
toc+='\n- [Spot vs Perpetual: user-confirmed comparison](#spot-vs-perpetual)'
parts.insert(1,toc)
for (title,body),anchor in zip(groups,anchors):parts.append('<a id="'+anchor+'"></a>\n\n## '+title+'\n\n'+clean(body))
parts.append(read('plan-execution.md'))
parts.append('<a id="spot-vs-perpetual"></a>\n\n'+read('spot-perpetual-comparison.md'))
parts.append('''## H. Research evidence, limits and validation record

This file is a proposed engineering/research plan, not a live trading service or a calibrated profitability forecast. Current primary documentation and pinned source were reviewed; bounded RSS GETs establish only access at that observation, not publication-to-phone speed. No new backtest,10k-agent load test, exchange order, paid subscription or paid model invocation was run for this plan. Earlier repository software tests are not financial validation of the proposed BTC/ETH system.

The requested “better” system has not passed its future acceptance gates because it has not been implemented. User explicitly chose spot-versus-perpetual comparison; exchange, capital, margin/leverage settings and jurisdiction remain unspecified. No live execution or leverage permission is inferred. Local software or a free tier still consumes hardware/quotas; Cloud-only Zep and paid news/model endpoints cannot be silently called free.

Evidence:

- [Markdown review manifest](planv1-evidence/md-review-inventory.json)
- [News primary sources and bounded RSS observations](planv1-evidence/news-sources.json)
- [Market data/backtest source ledger](planv1-evidence/sources-data.json)
- [Simulation/risk source ledger](planv1-evidence/sources-sim-risk.json)
- [Root methodology sources](planv1-evidence/method-sources.json)
- [Coverage, citations and arithmetic checks](planv1-evidence/validation.json)
- [Independent final review](planv1-evidence/cross-review.md)

External pages were checked on17November2026; entitlement, endpoint behavior and terms must be rechecked before implementation. Pinned GitHub links identify analyzed source, not a claim that current upstream HEAD matches it. Mechanical reference checks validate paths/line ranges, not every semantic inference or future strategy outcome.
''')
(b/'planv1.md').write_text('\n\n'.join(parts),encoding='utf-8')
print(json.dumps({'file':str(b/'planv1.md'),'words':len((b/'planv1.md').read_text(encoding='utf-8').split()),'bytes':(b/'planv1.md').stat().st_size}))
