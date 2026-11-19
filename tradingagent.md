# TradingAgents — source aur REA evidence se detailed analysis

Completed: 16 November 2026 (Asia/Kolkata). Language: Roman Hindi / Hinglish.

Yeh document actual inspected source ko explain karta hai. Isme naya trading feature, private authoring story, invented return, recommendation ya source fix add nahi kiya gaya. Source observations aur runtime-unverified claims alag hain. Original repository unchanged hai.

## Contents

- [1. Identity, scope aur construction](#1-identity-scope-aur-construction)
- [2. REA evidence aur independent archive check](#2-rea-evidence-aur-independent-archive-check)
- [3. Repository map aur counts](#3-repository-map-aur-counts)
- [4. Agent graph aur actual run](#4-agent-graph-aur-actual-run)
- [5. Data contracts, vendors aur model clients](#5-data-contracts-vendors-aur-model-clients)
- [6. Configuration: complete built-in key index](#6-configuration-complete-built-in-key-index)
- [7. CLI, entry points aur saved preferences](#7-cli-entry-points-aur-saved-preferences)
- [8. Portfolio input: context, ledger nahi](#8-portfolio-input-context-ledger-nahi)
- [9. Decision memory aur deferred reflection](#9-decision-memory-aur-deferred-reflection)
- [10. Backtest ka exact meaning aur limits](#10-backtest-ka-exact-meaning-aur-limits)
- [11. Outputs aur local file lifecycle](#11-outputs-aur-local-file-lifecycle)
- [12. Packaging, Docker, CI aur security boundaries](#12-packaging-docker-ci-aur-security-boundaries)
- [13. Verification, coverage aur explicit unknowns](#13-verification-coverage-aur-explicit-unknowns)
- [14. Full tracked file list aur evidence](#14-full-tracked-file-list-aur-evidence)

## 1. Identity, scope aur construction

Requested repository: https://github.com/TauricResearch/TradingAgents

Pinned commit: `9fa1196fffbcfd9de5146d2dd2869df84ab99838`. Git timestamp `2026-11-04T02:13:55-08:00`; subject `announce Trading-R1 official release`. Local source: `E:\coding\code\Trade\TradingAgents`. Clone shallow hai; full historical authorship/development sequence inspect nahi hui.

Package version `0.7.1` `tradingagents/__init__.py` se aati hai; setuptools dynamic version wahi read karta hai. Python requirement `>=3.11`. Apache2.0 license supplied hai. Python runtime used for verification3.13.5 on Windows. README ka Trading-R1 early-access product announcement is source package ka independently verified hosted implementation nahi hai.

Construction: Python modules + LangGraph state orchestration + LangChain model/tool clients + data-vendor adapters + typed Pydantic decisions + persisted Markdown memory + optional SQLite checkpoints + Typer/Rich terminal + Markdown/HTML reports. Separately trained per-role models/weights is tree mein establish nahi hote. Roles mostly prompts aur graph nodes hain. User-supplied market/portfolio input aur remote model outputs se decision reports bante hain; this graph is not a demonstrated broker execution engine.

Sources: [tradingagents/__init__.py:1-13](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/__init__.py#L1-L13), [pyproject.toml:1-65](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/pyproject.toml#L1-L65), [main.py:1-16](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/main.py#L1-L16), [LICENSE:1-8](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/LICENSE#L1-L8).

## 2. REA evidence aur independent archive check

Existing REA6.7.0 CLI used: `rea inspect-artifact E:/coding/code/Trade/tradingagent-evidence/source.zip --format json --full-output`. Input pinned Git commit ka locally created ZIP hai. REA static inventory ko runtime execution/decompilation/profitability claim nahi banaya gaya. Ordinary Python architecture source reading se established hai.

| REA field | Observed result |
| --- | --- |
| Evidence ID | `ev_49de5e326a1cdf49d1ef2800d33cf4c8f9847a56535a083f702bfed5a8027c7c` |
| SHA256 | `fafb75fd03c56f996cb416af19d0270203bff97659c639c2e8976b9adeafb522` |
| Provider | rea-artifact-graph |
| Graph nodes/occurrences/edges | 231/237/236 |
| Scope | complete-within-substeps; static ZIP inventory only |

Independent Git-blob comparison: all213tracked paths matched;17payloads byte-exact,196sirf CRLF/LF normalization ke baad matched; zero unmatched. ZIP comment inspected commit se match hai. Reported `complete-within-substeps` ZIP inventory tak limited hai; central-directory ke bahar non-entry bytes coverage mein nahi. Released executable ya private hosted product ka inventory nahi hua.

Evidence: [raw REA result](tradingagent-evidence/rea-artifact.json), [summary/hash/payload verification](tradingagent-evidence/rea-summary.json), [archive](tradingagent-evidence/source.zip), [verifier](tradingagent-evidence/verify-archive.py).

## 3. Repository map aur counts

| Tracked root item | Files |
| --- | --- |
| `.dockerignore` | 1 |
| `.env.enterprise.example` | 1 |
| `.env.example` | 1 |
| `.github` | 6 |
| `.gitignore` | 1 |
| `CHANGELOG.md` | 1 |
| `Dockerfile` | 1 |
| `LICENSE` | 1 |
| `README.md` | 1 |
| `assets` | 10 |
| `cli` | 11 |
| `docker-compose.yml` | 1 |
| `main.py` | 1 |
| `pyproject.toml` | 1 |
| `requirements.txt` | 1 |
| `tests` | 90 |
| `tradingagents` | 84 |

213tracked files;184Python files;88test files named test_*.py;1,009test_ function declarations;13,587non-test Python source lines. All184Python files AST-parse hue, no SyntaxError observed. Static test-function count runtime collection/parameterized cases/passing tests nahi hai.

Directories ka role: `tradingagents/agents` prompts, schemas, tools and state; `graph` orchestration/checkpoint/run propagation; `dataflows` routing/date/symbol/cache helpers and vendors; `llm_clients` model implementations/auth/catalog; `memory` log/settlement/reflection; `cli` terminal prompts/run/display/preferences/update notices. `assets` branding/illustrations; tests regression contracts. Full tracked inventory section14mein included hai.

Machine records: [inventory](tradingagent-evidence/inventory.json), [functions and source locations](tradingagent-evidence/function-catalog.json), [classes](tradingagent-evidence/class-catalog.json), [imports](tradingagent-evidence/import-catalog.json).

## 4. Agent graph aur actual run

```text
START
 +-> selected analysts (market / social / news / fundamentals)
 +-> Memory Log settlement/context
                | join all selected branches
        Bull <-> Bear research debate
                |
        Research Manager -> Trader proposal
                |
        Aggressive -> Conservative -> Neutral risk discussion
                | repeat configured rounds
        Portfolio Manager -> END
                |
        save state + decision memory, return final state/rating
```

Scope: local checkout `TradingAgents`, requested commit `9fa1196fffbcfd9de5146d2dd2869df84ab99838`. Neeche explanation actual Python implementation aur inspected tests par based hai. Is research mein live model, data API, broker ya exchange invoke nahi hua; tests ke assertions ko test coverage maana gaya hai, newly executed test result nahi.

### 1. Ek run mein asal mein kya hota hai

`TradingAgentsGraph` orchestration entry hai. Constructor config register karta hai, cache/results directories banata hai, deep aur quick model clients create karta hai, memory log/conditional routing/propagator/reflector initialize karta hai. Research Manager aur Portfolio Manager deep model use karte hain; analysts, researchers, trader aur risk debaters quick model use karte hain. Yeh distinct role prompts hain; har role ke liye separately trained model hone ka evidence nahi. [tradingagents/graph/trading_graph.py:69](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L69) [tradingagents/graph/setup.py:125](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L125)

Programmatic `propagate(company_name, trade_date, asset_type="stock", portfolio=None)` pehle date ko exact `YYYY-MM-DD` aur non-future validate karta hai. Phir run-local config aur optional checkpoint scope mein `_run_graph` execute hota hai. Initial state mein ticker, asset mode, trade date, resolved instrument identity aur caller-supplied portfolio ka rendered context aata hai. Instrument resolution run start par deterministic identity lookup hai; yeh LLM se company guess karwane ki jagah prompt mein context inject karta hai. [tradingagents/graph/trading_graph.py:30](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L30) [tradingagents/graph/trading_graph.py:167](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L167) [tradingagents/graph/trading_graph.py:293](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L293)

Default analyst selection `market`, `social`, `news`, `fundamentals` hai. `social` saved-config key hai, lekin graph node ka naam `Sentiment Analyst` hai. Selection plan order preserve karta hai, unknown keys aur empty selection reject karta hai. Order preserve hone ka matlab sequential execution nahi: graph `START` se har selected analyst aur Memory Log ko edges deta hai. List-based join sab branches finish hone ke baad Bull Researcher start karta hai. [tradingagents/graph/analyst_execution.py:20](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/analyst_execution.py#L20) [tradingagents/graph/analyst_execution.py:49](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/analyst_execution.py#L49) [tradingagents/graph/setup.py:157](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L157)

Run ka concrete route: `START → selected analysts + Memory Log → Bull Researcher ↔ Bear Researcher → Research Manager → Trader → Aggressive → Conservative → Neutral → Portfolio Manager → END`. Analyst phase parallel hai; research aur risk debates turn-by-turn sequential hain. Portfolio Manager ke baad execution ya monitoring node nahi laga. [tradingagents/graph/setup.py:164](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L164) [tradingagents/graph/setup.py:168](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L168) [tradingagents/graph/setup.py:185](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L185)

### 2. Parallel analysts ka isolation aur tool-loop control

Har analyst apna compiled subgraph hai. Input schema `AgentState` ho sakta hai, lekin output schema sirf us analyst ka report field expose karta hai. Isliye Market Analyst ke tool calls News Analyst ke chat history mein merge nahi hote; parallel branches same state key write bhi nahi karti. Parent ko market/news/fundamentals/sentiment reports milte hain, unke raw private tool transcripts nahi. [tradingagents/graph/setup.py:53](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L53)

Tool-using analyst `agent → tools → agent` repeat karta hai. `AIMessage.tool_calls` present ho to `ToolNode` invoke hota hai; otherwise report complete aur subgraph END. `max_tool_rounds` tool-calling messages ki count hai, individual tool calls ki count nahi: ek response mein multiple calls ek round hain. Limit par extra wrap-up turn chalta hai aur uske baad unconditional END hai. [tradingagents/graph/setup.py:48](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L48) [tradingagents/graph/setup.py:70](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L70)

Wrap-up mein model ko tools bind nahi kiye jaate. Purane calls aur ToolMessages plain text mein rewrite hote hain, taaki provider unbound-tool history refuse na kare. Report missing data explicitly batane ko kehta hai. Constructor unsafe combination `2 * max_tool_rounds + 2 >= max_recur_limit` reject karta hai. Yeh runaway loops ka operational guard hai; report factual completeness ki guarantee nahi. [tradingagents/agents/analysts/turn.py:13](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/turn.py#L13) [tradingagents/agents/analysts/turn.py:30](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/turn.py#L30) [tradingagents/graph/trading_graph.py:88](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L88)

### 3. Analyst roles aur actual tools

Market Analyst ke actual tools `get_stock_data`, `get_indicators`, `get_verified_market_snapshot` hain. Prompt up to eight complementary indicators choose karne, stock data first lene, aur exact OHLCV/price/indicator claims verified snapshot se anchor karne ko kehta hai. SMA/EMA, MACD variants, RSI, Bollinger, ATR aur VWMA listed hain. Snapshot conflict ho to discrepancy flag karna prompt instruction hai; har generated claim ka deterministic post-validation pass yahan nahi. [tradingagents/agents/analysts/market_analyst.py:8](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/market_analyst.py#L8) [tradingagents/agents/analysts/market_analyst.py:22](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/market_analyst.py#L22) [tradingagents/agents/analysts/market_analyst.py:46](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/market_analyst.py#L46)

News Analyst `get_news`, `get_global_news`, `get_macro_indicators`, `get_prediction_markets` access karta hai. Recent company/asset news, macro environment, FRED indicators aur event probabilities uska scope hai. Yeh tools offered hain; ordinary turn mein model decide karta hai kaunsa call kare. Date aur instrument context prompt mein injected hain. [tradingagents/agents/analysts/news_analyst.py:13](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/news_analyst.py#L13) [tradingagents/agents/analysts/news_analyst.py:28](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/news_analyst.py#L28)

Fundamentals Analyst ko `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement`, `get_insider_transactions` milte hain. Crypto mode mein ordinary company-fundamentals coverage limited hone ka context downstream researchers tak jaata hai; source listing ko universal crypto valuation support nahi samajhna chahiye. [tradingagents/agents/analysts/fundamentals_analyst.py:14](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/fundamentals_analyst.py#L14) [tradingagents/agents/researchers/bull_researcher.py:23](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/researchers/bull_researcher.py#L23)

Sentiment Analyst alag pattern follow karta hai: model ko data tools bind nahi hote. Node seven-day news, StockTwits aur Reddit inputs code se prefetch karta hai, social posts screen karta hai, phir blocks prompt mein inject karta hai. `SentimentReport` structured path mein six sentiment bands, bounded 0–10 score, confidence aur narrative leta hai. Score/band consistency guidance hai; schema description khud kehti hai numeric bounds hi enforced hain. Historical social inputs available feeds tak limited hain, archived point-in-time completeness guaranteed nahi. [tradingagents/agents/analysts/sentiment_analyst.py:43](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/sentiment_analyst.py#L43) [tradingagents/agents/analysts/sentiment_analyst.py:63](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/sentiment_analyst.py#L63) [tradingagents/agents/analysts/sentiment_analyst.py:109](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/sentiment_analyst.py#L109) [tradingagents/agents/schemas.py:296](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/schemas.py#L296)

### 4. Research debate se trade proposal

Bull Researcher reports ko growth, competitive advantages aur positive indicators ke favour mein argue karta hai; Bear risks, weaknesses aur negative indicators par counter-case banata hai. Dono prior debate aur opponent response read karte hain, apna labelled argument history mein append karke count increment karte hain. Yeh extra external research calls nahi: researcher functions plain `llm.invoke(prompt)` use karte hain. [tradingagents/agents/researchers/bull_researcher.py:18](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/researchers/bull_researcher.py#L18) [tradingagents/agents/researchers/bull_researcher.py:31](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/researchers/bull_researcher.py#L31) [tradingagents/agents/researchers/bear_researcher.py:31](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/researchers/bear_researcher.py#L31) [tradingagents/agents/researchers/bear_researcher.py:53](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/researchers/bear_researcher.py#L53)

Router `count >= 2 * max_debate_rounds` par Research Manager bhejta hai; otherwise Bull-labelled latest response ke baad Bear, aur fallback Bull. Thus rounds language ka practical matlab har side ke configured turns hai. Research Manager debate history judge karke five-tier recommendation, rationale aur strategic actions produce karta hai. Prompt conflict ko automatic Hold banane se rokta hai, lekin balanced/thin evidence par Hold allow karta hai. [tradingagents/graph/conditional_logic.py:12](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/conditional_logic.py#L12) [tradingagents/agents/managers/research_manager.py:23](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/managers/research_manager.py#L23) [tradingagents/agents/schemas.py:95](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/schemas.py#L95)

Trader research plan, optional market report aur actual caller portfolio context read karta hai. Market report present ho to entry/stop/sizing ko technical levels se ground karne instruction milti hai. Output `Buy/Hold/Sell`, reasoning, optional absolute entry price, stop loss aur textual sizing hai. Overweight ko Buy aur Underweight ko Sell translate karne guidance hai. Trader orders submit nahi karta; `trader_investment_plan` markdown proposal return karta hai. [tradingagents/agents/trader/trader.py:23](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/trader/trader.py#L23) [tradingagents/agents/trader/trader.py:46](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/trader/trader.py#L46) [tradingagents/agents/trader/trader.py:76](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/trader/trader.py#L76) [tradingagents/agents/trader/trader.py:93](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/trader/trader.py#L93)

### 5. Risk discussion aur final state

Aggressive voice upside/high-risk opportunities champion karta hai, Conservative capital preservation/downside critique, Neutral moderate risk/reward balance. Yeh trader proposal, reports aur portfolio context par debate hain; mathematical risk-engine veto, enforced position limit ya broker pre-trade check nahi. Risk router latest speaker se Aggressive→Conservative→Neutral cycle banata hai aur `count >= 3 * max_risk_discuss_rounds` par Portfolio Manager bhejta hai. [tradingagents/agents/risk_mgmt/aggressive_debator.py:23](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/risk_mgmt/aggressive_debator.py#L23) [tradingagents/agents/risk_mgmt/conservative_debator.py:32](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/risk_mgmt/conservative_debator.py#L32) [tradingagents/agents/risk_mgmt/neutral_debator.py:32](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/risk_mgmt/neutral_debator.py#L32) [tradingagents/graph/conditional_logic.py:23](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/conditional_logic.py#L23)

Portfolio Manager research plan, trader proposal, risk history, caller portfolio aur available past lessons synthesize karta hai. Structured `PortfolioDecision` mein five-tier rating, executive summary, investment thesis, optional price target aur horizon hain. Typed rating directly `final_rating` banti hai; markdown `final_trade_decision` separately rendered hota hai. Isse thesis mein quoted kisi aur rating ko decision maan lene ka risk reduce hota hai. [tradingagents/agents/managers/portfolio_manager.py:26](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/managers/portfolio_manager.py#L26) [tradingagents/agents/managers/portfolio_manager.py:78](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/managers/portfolio_manager.py#L78) [tradingagents/agents/schemas.py:221](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/schemas.py#L221)

`AgentState` mein reports/plans strings, nested debate histories/counts aur final fields hain. Structured outputs all stages mein typed objects ke roop mein permanently retained nahi: renderers mostly markdown state banate hain. Unsupported structured binding ya failed structured invocation par free-text fallback hota hai. PM fallback labelled text parse karta hai; unparsable result REVIEW ho sakta hai. Optional numeric prices mein nullish, percentage aur non-single-number text drop hota hai; source mathematical price plausibility prove nahi karta. [tradingagents/agents/state.py:45](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/state.py#L45) [tradingagents/agents/structured.py:42](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/structured.py#L42) [tradingagents/agents/structured.py:59](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/structured.py#L59) [tradingagents/agents/schemas.py:33](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/schemas.py#L33) [tradingagents/graph/trading_graph.py:177](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L177)

### 6. Persistence, resume aur reflection

Checkpoint enabled ho to per-ticker SQLite `SqliteSaver` ke saath workflow recompile hota hai. Thread identity ticker/date plus signature se banti hai. Signature analysts, debate/risk depth, asset type, portfolio fingerprint, graph layout markers aur config digest include karti hai; output paths/checkpoint toggle/retry count excluded hain. Changed analysis settings stale reports reuse karne ke bajay fresh thread banate hain. Resume input `None` hai, initial state dobara nahi, taaki message reducer duplicates na banaye. Success par thread rows clear hote hain; finally saver close aur plain graph restore hota hai. [tradingagents/graph/checkpointer.py:19](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/checkpointer.py#L19) [tradingagents/graph/trading_graph.py:140](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L140) [tradingagents/graph/trading_graph.py:192](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L192) [tradingagents/graph/trading_graph.py:221](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L221) [tradingagents/graph/trading_graph.py:247](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L247)

Memory Log parallel step all tickers ki due pending decisions settle karne ki koshish karta hai, then historical analysis date ke as-of lessons load karta hai. Failures `memory_note` mein aate hain aur analysis continue kar sakta hai. Only PM lessons explicitly prompt mein padhta hai. Reflection interface `reflect_on_final_decision(final_decision, raw_return, alpha_return, benchmark_name="SPY", holding_days=5)` quick LLM se 2–4 sentences ki lesson mangta hai; model weights update nahi hote. Newly completed decision memory mein pending store hoti hai, future settlement ke liye. [tradingagents/graph/trading_graph.py:309](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L309) [tradingagents/graph/trading_graph.py:359](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L359) [tradingagents/memory/reflection.py:13](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/memory/reflection.py#L13) [tradingagents/memory/reflection.py:36](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/memory/reflection.py#L36)

### 7. README claim aur test evidence ki boundary

README line 106 approved order simulated exchange ko bhejne/execution ka claim karta hai. Inspected execution path us claim ko implement nahi karta: PM→END ke baad `_run_graph` decision record karta hai, checkpoint clear karta hai, `(final_state, rating)` return karta hai. Actual tool inventory market/fundamental/news/macro inputs ka hai, order placement tool ka nahi. Is checkout ko research/recommendation workflow samajhna supported conclusion hai; executable simulated-exchange integration claim supported nahi. [README.md:106](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/README.md#L106) [tradingagents/graph/setup.py:185](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/setup.py#L185) [tradingagents/graph/trading_graph.py:373](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L373) [tradingagents/agents/tools.py:18](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L18)

Inspected end-to-end tests scripted models aur mocked vendor data use karte hain. They assert all reports/plans and final Overweight rating, tool-route coverage, pending memory record, interrupted resume needing only remaining calls, concurrent analyst threads, bounded tool loops, streaming and memory-failure continuity. Yeh wiring evidence hai, profitable trading ya live-provider correctness evidence nahi. Is notes pass mein tests read kiye gaye; execution result parent ki verification report se alag record hona chahiye. [tests/test_graph_end_to_end.py:50](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_graph_end_to_end.py#L50) [tests/test_graph_end_to_end.py:102](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_graph_end_to_end.py#L102) [tests/test_graph_end_to_end.py:133](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_graph_end_to_end.py#L133) [tests/test_graph_end_to_end.py:151](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_graph_end_to_end.py#L151) [tests/test_graph_end_to_end.py:182](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_graph_end_to_end.py#L182) [tests/test_graph_end_to_end.py:257](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_graph_end_to_end.py#L257) [tests/test_graph_end_to_end.py:334](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_graph_end_to_end.py#L334)

## 5. Data contracts, vendors aur model clients

Scope: `9fa1196fffbcfd9de5146d2dd2869df84ab99838` checkout ke source aur selected tests ka static inspection. Yahan “supported” ka matlab implementation mein available contract hai; live vendor availability, paid entitlement, model access ya production reliability verify nahin ki gayi. Koi live API/LLM call, install ya source change nahin hua. Neeche references repository-relative hain.

### Request ka actual safar

Analyst ke decorated tools se request router tak jaati hai. Dated tools `company_of_interest` aur `trade_date` graph state se `InjectedState` mein lete hain; model ko instrument/date authority dene ke bajay model-requested date ko run date tak clamp kiya jaata hai. `get_stock_data` aur `get_news` windows normalize karte hain; invalid start ya reversed range par model ko guidance string milti hai. Indicators comma-separated aayein to tool unhe individual calls mein todta hai. Verified snapshot ka tool router bypass karke seedha Yahoo snapshot builder use karta hai—configured price vendor badalne se snapshot vendor nahin badalta. [tradingagents/agents/tools.py:19](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L19) [tradingagents/agents/tools.py:42](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L42) [tradingagents/agents/tools.py:73](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L73) [tradingagents/agents/tools.py:172](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L172)

`as_of` earlier valid requested date rakhta hai; missing, invalid ya future request ko trade date banata hai. Empty trade date, jaise direct Python invocation, clamp disable kar deti hai. `as_of_window` wholly future window ko uski duration preserve karke peeche shift karta hai. Isliye graph tools ki protection ko har raw vendor function ka independent global guarantee samajhna galat hoga. UTC item-window `[start, end+1 day)` hai; naive timestamps UTC assume hote hain. Undated item sirf present tak pahunchte window mein acceptable hai. [tradingagents/dataflows/date_window.py:77](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py#L77) [tradingagents/dataflows/date_window.py:93](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py#L93) [tradingagents/dataflows/date_window.py:17](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py#L17)

Run-specific config `ContextVar` mein bind hota hai; nested configuration one level deep merge hoti hai, return par deep copy milti hai. Yeh same process mein multiple graph runs ke vendors/settings mix hone se bachata hai; external vendor ya SDK isolation ka claim nahin hai. Tool-level `tool_vendors` category ke `data_vendors` ko override karta hai. [tradingagents/dataflows/config.py:13](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/config.py#L13) [tradingagents/dataflows/config.py:26](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/config.py#L26) [tradingagents/dataflows/config.py:44](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/config.py#L44) [tradingagents/dataflows/router.py:160](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/router.py#L160)

Router ka comma-separated explicit vendor list hi exact fallback chain hai. Unchosen vendor silently add nahin hota. `default` sentinel par registered implementations ka insertion order use hota hai. Explicit chain mein method-unsupported entries filter hote hain; ek bhi supported vendor na bache to `ValueError`. First returned value immediate success hai—empty/withheld prose bhi—router content inspect karke next vendor nahin try karta. Default category prices/indicators/news Yahoo; statements category `sec_edgar,yfinance`, macro FRED aur event odds Polymarket hai. SEC overview nahin deta, isliye same category ke overview call mein Yahoo bachta hai. [tradingagents/dataflows/router.py:202](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/router.py#L202) [tradingagents/dataflows/router.py:233](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/router.py#L233) [tradingagents/default_config.py:165](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L165)

### Failure ka matlab

Three behavioral types hain: `NoMarketDataError` usable data absent/stale, `VendorUnavailableError` request failed/throttled, aur `VendorNotConfiguredError` missing configuration. Router sab par chosen next vendor try karta hai. Entire chain ke baad unavailable vendor ho to `DATA_UNAVAILABLE`; only clean no-data answers par `NO_DATA_AVAILABLE`, instrument ko invalid declare karna zaroori nahin. Generic failure plus no-data bhi unavailable ban jaata hai. Sirf configuration/untyped errors bache to core category first error raise karti hai, macro/prediction optional categories sentinel mein degrade hoti hain. Sentinels model ko numbers fabricate na karne ki explicit instruction dete hain, deterministic enforcement nahin. [tradingagents/dataflows/errors.py:1](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/errors.py#L1) [tradingagents/dataflows/router.py:178](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/router.py#L178) [tradingagents/dataflows/router.py:257](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/router.py#L257)

### Yahoo prices aur deterministic verification

Yahoo path broker/forex/crypto aliases normalize karta hai; example `XAUUSD+` gold futures `GC=F` tak resolve hota hai. Yeh source instrument proxy ho sakta hai: symbol normalization execution venue/contract equivalence guarantee nahin. Cache filename ke liye separate safe ticker validator path escape reject karta hai. Raw requested range `Ticker.history` ko inclusive end dene ke liye next calendar day request karta hai, timezone wall-clock preserve karke drop karta hai, aur latest row requested date se 10 calendar days se zyada purani ho to stale error deta hai. [tradingagents/dataflows/symbols.py:51](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/symbols.py#L51) [tradingagents/dataflows/symbols.py:103](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/symbols.py#L103) [tradingagents/dataflows/symbols.py:155](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/symbols.py#L155) [tradingagents/dataflows/vendors/yahoo/market.py:18](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/market.py#L18)

Indicators aur verification `load_ohlcv` use karte hain: today tak latest five-year download, `auto_adjust=True`, actions excluded, one CSV per canonical symbol. Cache previous download day ka ho to refetch; same-day historical request reuse kar sakti hai, current-day request ke liye 900-second TTL hai, kyunki today's candle partial ho sakti hai. Date cleanup local market date preserve karta hai; future rows cutoff se remove hoti hain. Latest closeless rows drop hoti hain; indicator path remaining gaps forward/back-fill kar sakta hai. Exact-price snapshot `fill_gaps=False` use karta hai aur defensive cutoff dobara lagata hai. [tradingagents/dataflows/vendors/yahoo/ohlcv.py:45](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/ohlcv.py#L45) [tradingagents/dataflows/vendors/yahoo/ohlcv.py:147](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/ohlcv.py#L147) [tradingagents/dataflows/vendors/yahoo/ohlcv.py:159](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/ohlcv.py#L159) [tradingagents/dataflows/vendors/yahoo/ohlcv.py:249](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/ohlcv.py#L249) [tradingagents/dataflows/vendors/yahoo/snapshot.py:33](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/snapshot.py#L33)

Snapshot latest OHLCV, fixed indicators aur maximum 30 recent rows deterministically computes karta hai; unsupported indicator `N/A` ban sakta hai. “Verified” ka matlab supplied Yahoo rows se computation, independent exchange reconciliation nahin. Historical dates trim hone ke bawajood current adjusted history historical vintage archive nahin hai; future splits/revisions ke against as-known-price guarantee source mein nahin. Five-year-from-today download older requested histories ke liye bhi availability limit hai. Yahoo wrapper 429 par 2/4/8-second backoff, total four attempts; other errors unavailable banate hain. Empty result par reachability HEAD probe absence versus outage distinguish karne ki heuristic hai, complete vendor health check nahin. [tradingagents/dataflows/vendors/yahoo/snapshot.py:73](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/snapshot.py#L73) [tradingagents/dataflows/vendors/yahoo/common.py:32](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/common.py#L32) [tradingagents/dataflows/vendors/yahoo/common.py:69](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/common.py#L69)

### Statements: SEC ki strength, baaki ki withholding

Historical Yahoo/Alpha Vantage company profile completely withheld hai: valuation hi nahin, name/sector bhi current snapshot hai. Unke financial statements aur insider trades bhi historical date par withheld hote hain; period end public filing time nahin, trade execution disclosure time nahin. Yeh intentional missing-data contract hai, historical coverage ka substitute nahin. Tests verify karte hain ki withheld request vendor ko call tak nahin karti. [tradingagents/dataflows/date_window.py:119](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py#L119) [tradingagents/dataflows/date_window.py:145](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py#L145) [tradingagents/dataflows/date_window.py:164](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py#L164) [tests/test_statement_knowledge_time.py:25](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_statement_knowledge_time.py#L25)

SEC EDGAR public ticker map aur companyfacts fetch karta hai; account/key nahin, identifying User-Agent chahiye, env `SEC_EDGAR_USER_AGENT` override hai. Ticker current map mein absent ya `us-gaap` facts absent hon to no-data. JSON cache TTL 24 hours. `_as_of` fact `filed <= as_of_date` rakhta hai aur period/span ka latest eligible filing leta hai; amendment sirf amendment filing day se effect karta hai. Alternative revenue tags summed nahin, first available period tag preferred hai. USD millions aur EPS/custom units separate render hote hain. [tradingagents/dataflows/vendors/sec_edgar.py:93](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py#L93) [tradingagents/dataflows/vendors/sec_edgar.py:123](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py#L123) [tradingagents/dataflows/vendors/sec_edgar.py:154](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py#L154) [tradingagents/dataflows/vendors/sec_edgar.py:191](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py#L191)

Quarter/year duration ranges separate hain; quarterly cashflow agar only six/nine-month YTD available ho to explicit span label milta hai. Fourth quarter subtraction se manufacture nahin hota. Annual output fiscal periods ke liye annual forms require karta hai. Limitation: selected line items, current ticker identity map, US-gaap-tag coverage, filing-date granularity; intraday publication timestamp nahin. Yeh full filing parser ya universal global financial database nahin. [tradingagents/dataflows/vendors/sec_edgar.py:44](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py#L44) [tradingagents/dataflows/vendors/sec_edgar.py:79](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py#L79) [tradingagents/dataflows/vendors/sec_edgar.py:205](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py#L205) [tradingagents/dataflows/vendors/sec_edgar.py:258](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py#L258)

### News, macro, prediction aur social

Yahoo ticker-news quote feed first, empty ho to symbol-tagged search articles; neither answers/no tagged coverage par unavailable. Nested/flat article dates parse hote hain; range filter ke baad no items ho to `coverage_gap` old unobserved window ko genuine silence nahin kehta. Global Yahoo news relevance searches merge karta hai, title deduplicate karta hai, filter ke baad article limit count karta hai. Recent feed mein dated result milna archival completeness ka proof nahin. [tradingagents/dataflows/vendors/yahoo/news.py:17](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/news.py#L17) [tradingagents/dataflows/vendors/yahoo/news.py:87](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/news.py#L87) [tradingagents/dataflows/vendors/yahoo/news.py:137](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/yahoo/news.py#L137) [tradingagents/dataflows/date_window.py:45](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py#L45)

Alpha Vantage `ALPHA_VANTAGE_API_KEY`, 30s timeout aur query `source=trading_agents` use karta hai. Daily adjusted stock CSV compact/full choose karke date-filter hota hai; parse failure swallow nahin hoti. News `NEWS_SENTIMENT` server `time_from/time_to` aur capped limit par rely karta hai; end date 23:59 hai. Yahoo jaise local article-by-article timestamp filter yahan nahin. Indicator results bhi requested historical date/window tak select hote hain. Notice phrases rate-limit/premium versus invalid-key classify karti hain; malformed/rejected call ko instrument no-data nahin kaha jaata. [tradingagents/dataflows/vendors/alpha_vantage/common.py:90](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/alpha_vantage/common.py#L90) [tradingagents/dataflows/vendors/alpha_vantage/common.py:156](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/alpha_vantage/common.py#L156) [tradingagents/dataflows/vendors/alpha_vantage/stock.py:9](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/alpha_vantage/stock.py#L9) [tradingagents/dataflows/vendors/alpha_vantage/news.py:10](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/alpha_vantage/news.py#L10) [tradingagents/dataflows/vendors/alpha_vantage/indicator.py:187](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/alpha_vantage/indicator.py#L187)

FRED key `FRED_API_KEY` hai. Alias/raw series ID se metadata aur observations dono fetch hote hain. Observation-end cutoff ke saath `realtime_start=realtime_end=min(as_of_date, Chicago-today)` vintage pin hai: revised GDP/CPI ko today's revision se historical run mein inject nahin karna. Default lookback 365 days, displayed final 40 points; change full fetched first/last observation ke beech hai. Missing `.` skip; unavailable vintage empty explanation deta hai. Yeh actual vintage-aware path hai, lekin ALFRED coverage/publication availability jitni hi. [tradingagents/dataflows/vendors/fred.py:102](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/fred.py#L102) [tradingagents/dataflows/vendors/fred.py:167](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/fred.py#L167) [tradingagents/dataflows/vendors/fred.py:195](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/fred.py#L195)

Polymarket public Gamma search keyless hai; past date par network se pehle withheld. Live open forward-looking markets traded volume se rank hote hain, first outcome probability, volume, resolution date, weekly move render hota hai. It is priced odds context, calibrated proprietary prediction engine nahin. [tradingagents/dataflows/vendors/polymarket.py:32](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/polymarket.py#L32) [tradingagents/dataflows/vendors/polymarket.py:50](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/polymarket.py#L50) [tradingagents/dataflows/vendors/polymarket.py:86](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/polymarket.py#L86)

Sentiment node seven-day news, StockTwits aur Reddit prefetch karke prompt mein inject karta hai. StockTwits public symbol stream, crypto `BTC.X`; Reddit anonymous RSS combined subreddit search, newest 100, `t=week`, per-subreddit five posts default. Reddit 429 par one retry, Retry-After/fallback roughly 60 seconds, feed body capped 5MB. Both timestamp filters historical future chatter remove karte hain; old inaccessible windows unavailable, archived social reconstruction unsupported. StockTwits percentages user-labelled messages ke sample counts hain. [tradingagents/agents/analysts/sentiment_analyst.py:56](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/analysts/sentiment_analyst.py#L56) [tradingagents/dataflows/vendors/stocktwits.py:74](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/stocktwits.py#L74) [tradingagents/dataflows/vendors/reddit.py:105](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/reddit.py#L105) [tradingagents/dataflows/vendors/reddit.py:175](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/reddit.py#L175) [tradingagents/dataflows/vendors/reddit.py:248](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/reddit.py#L248)

Optional Jev screening `TYPESAFE_API_KEY` par activate hoti hai; post text/instrument external TypeSafe/custom base endpoint ko bhejti hai. Up to 16 workers, three attempts, 15s request timeout; low relevance posts drop, uncertain keep. Any screening failure keeps posts unscreened with note. Historical instrument context current company name ko explicit identity-only label karta hai aur current sector/exchange hide karta hai; Jev resolver current profile identity separately use karta hai. [tradingagents/agents/post_screen.py:66](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/post_screen.py#L66) [tradingagents/agents/post_screen.py:134](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/post_screen.py#L134) [tradingagents/agents/post_screen.py:173](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/post_screen.py#L173) [tradingagents/agents/context.py:106](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/context.py#L106)

### LLM clients aur trust boundary

Factory native Anthropic/Google/Azure/Bedrock lazily selects karti hai, remaining supported names OpenAI-compatible registry se. Quick/deep tiers separate provider/model/endpoint le sakte hain; different provider ko main backend URL inherit nahin hota. Temperature, retries, token cap forwarded, Gemini cap `max_output_tokens`; booleans/negative retry and nonpositive cap rejected. Unknown model mostly warning-and-continue hai; local/relays/Bedrock/ChatGPT any ID accept. Model catalog access entitlement verification nahin. [tradingagents/llm_clients/factory.py:6](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/factory.py#L6) [tradingagents/llm_clients/factory.py:102](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/factory.py#L102) [tradingagents/llm_clients/factory.py:153](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/factory.py#L153) [tradingagents/llm_clients/base_client.py:41](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/base_client.py#L41) [tradingagents/llm_clients/validators.py:7](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/validators.py#L7)

Registry OpenAI, xAI, DeepSeek, international/China Qwen/GLM/MiniMax, OpenRouter, Mistral, Kimi, Groq, NVIDIA, Ollama, ChatGPT, generic endpoint rakhti hai. URL precedence explicit, provider env, default; generic URL required, local keys optional. Native OpenAI endpoint Responses API, custom gateway Chat Completions. Capabilities structured method/tool_choice choose karti hain; DeepSeek reasoning_content roundtrip, MiniMax reasoning_split special handling hai. Content block normalization reasoning blocks ko report text se hataata hai, outgoing history ka privacy filter nahin. [tradingagents/llm_clients/openai_client.py:19](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/openai_client.py#L19) [tradingagents/llm_clients/openai_client.py:93](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/openai_client.py#L93) [tradingagents/llm_clients/openai_client.py:129](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/openai_client.py#L129) [tradingagents/llm_clients/openai_client.py:276](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/openai_client.py#L276) [tradingagents/llm_clients/openai_client.py:344](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/openai_client.py#L344) [tradingagents/llm_clients/base_client.py:6](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/base_client.py#L6)

Google default timeout 600s/minimal-thinking fallback; Anthropic effort model-gated; Azure deployment env fallback; Bedrock optional dependency, bearer token preferred over AWS chain, region env/default us-west-2. Retry config delegates SDK behavior; no universal bespoke LLM retry orchestration/context-window tokenizer here. [tradingagents/llm_clients/google_client.py:44](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/google_client.py#L44) [tradingagents/llm_clients/anthropic_client.py:60](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/anthropic_client.py#L60) [tradingagents/llm_clients/azure_client.py:35](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/azure_client.py#L35) [tradingagents/llm_clients/bedrock_client.py:52](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/bedrock_client.py#L52)

ChatGPT sign-in token API-key se separate, pinned OpenAI endpoint only. Plan wrapper streams, `store=False`, system→developer, temperature/top_p/max_tokens drop, API organization/project clear. OAuth PKCE/state/nonce, RS256 issuer/audience/expiry validation, atomically saved token file with mode 0600; plaintext token record encrypted vault nahin. Refresh shared lock mein rotated token reload karta hai, five-minute margin, transient failure mein valid token use aur one-minute retry cooldown. Windows ACL enforcement ko POSIX mode alone se assume nahin karna. [tradingagents/llm_clients/openai_client.py:165](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/openai_client.py#L165) [tradingagents/llm_clients/openai_client.py:305](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/openai_client.py#L305) [tradingagents/llm_clients/chatgpt_auth.py:75](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/chatgpt_auth.py#L75) [tradingagents/llm_clients/chatgpt_auth.py:119](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/chatgpt_auth.py#L119) [tradingagents/llm_clients/chatgpt_auth.py:228](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/chatgpt_auth.py#L228) [tradingagents/llm_clients/chatgpt_auth.py:365](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/llm_clients/chatgpt_auth.py#L365)

AV/FRED query keys error strings se scrub, request/response exception attachments remove hote hain; general full-pipeline redaction guarantee nahin. Atomic cache replacement prevents partial writes; ordinary cache permissions encrypted/private storage promise nahin. Configured remote model receives prompt/report/history/tool data, optional Jev receives social text; local provider choosing alone baaki market-data/Jev network calls disable nahin karta. Read tests cover withholding, date injection, recent-feed coverage, tier URL isolation and sign-in refresh races; test code inspected, yahan execute nahin kiya. [tradingagents/dataflows/net.py:6](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/net.py#L6) [tradingagents/dataflows/files.py:14](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/files.py#L14) [tests/test_tool_date_enforcement.py:70](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_tool_date_enforcement.py#L70) [tests/test_social_lookahead.py:155](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_social_lookahead.py#L155) [tests/test_tier_providers.py:42](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_tier_providers.py#L42) [tests/test_chatgpt_auth.py:182](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_chatgpt_auth.py#L182)

### All agent tool wrapper definitions

| Tool function | Source |
| --- | --- |
| `get_stock_data` | [tradingagents/agents/tools.py:19](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L19) |
| `get_indicators` | [tradingagents/agents/tools.py:42](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L42) |
| `get_verified_market_snapshot` | [tradingagents/agents/tools.py:73](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L73) |
| `get_fundamentals` | [tradingagents/agents/tools.py:98](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L98) |
| `get_balance_sheet` | [tradingagents/agents/tools.py:115](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L115) |
| `get_cashflow` | [tradingagents/agents/tools.py:134](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L134) |
| `get_income_statement` | [tradingagents/agents/tools.py:153](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L153) |
| `get_news` | [tradingagents/agents/tools.py:172](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L172) |
| `get_global_news` | [tradingagents/agents/tools.py:195](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L195) |
| `get_insider_transactions` | [tradingagents/agents/tools.py:219](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L219) |
| `get_macro_indicators` | [tradingagents/agents/tools.py:233](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L233) |
| `get_prediction_markets` | [tradingagents/agents/tools.py:268](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/tools.py#L268) |

## 6. Configuration: complete built-in key index

Neeche values source ke pre-environment default expressions hain, machine ke actual credentials/config values nahi. `build_default_config()` import-time DEFAULT_CONFIG ke liye environment fold karta hai; function dobara call karne par current environment reread hota hai. Python callers explicit keys override kar sakte hain. `DEFAULT_CONFIG.copy()` shallow dict copy hai; run-local dataflows config helpers nested dicts ke isolation/merge rules independently implement karte hain.

| Config key | Built-in source expression | Source |
| --- | --- | --- |
| `results_dir` | `os.getenv('TRADINGAGENTS_RESULTS_DIR') or os.path.join(_TRADINGAGENTS_HOME, 'logs')` | [tradingagents/default_config.py:84](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L84) |
| `data_cache_dir` | `os.getenv('TRADINGAGENTS_CACHE_DIR') or os.path.join(_TRADINGAGENTS_HOME, 'cache')` | [tradingagents/default_config.py:85](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L85) |
| `memory_log_path` | `os.getenv('TRADINGAGENTS_MEMORY_LOG_PATH') or os.path.join(_TRADINGAGENTS_HOME, 'memory', 'trading_memory.md')` | [tradingagents/default_config.py:86](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L86) |
| `memory_log_max_entries` | `None` | [tradingagents/default_config.py:90](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L90) |
| `llm_provider` | `'openai'` | [tradingagents/default_config.py:92](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L92) |
| `deep_think_llm` | `'gpt-6-sol'` | [tradingagents/default_config.py:93](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L93) |
| `quick_think_llm` | `'gpt-6-luna'` | [tradingagents/default_config.py:94](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L94) |
| `backend_url` | `None` | [tradingagents/default_config.py:100](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L100) |
| `quick_think_provider` | `None` | [tradingagents/default_config.py:104](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L104) |
| `deep_think_provider` | `None` | [tradingagents/default_config.py:105](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L105) |
| `quick_think_backend_url` | `None` | [tradingagents/default_config.py:106](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L106) |
| `deep_think_backend_url` | `None` | [tradingagents/default_config.py:107](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L107) |
| `google_thinking_level` | `None` | [tradingagents/default_config.py:109](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L109) |
| `openai_reasoning_effort` | `None` | [tradingagents/default_config.py:110](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L110) |
| `anthropic_effort` | `None` | [tradingagents/default_config.py:111](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L111) |
| `temperature` | `None` | [tradingagents/default_config.py:116](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L116) |
| `llm_max_retries` | `None` | [tradingagents/default_config.py:120](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L120) |
| `max_tokens` | `None` | [tradingagents/default_config.py:125](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L125) |
| `checkpoint_enabled` | `False` | [tradingagents/default_config.py:128](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L128) |
| `output_language` | `'English'` | [tradingagents/default_config.py:131](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L131) |
| `max_debate_rounds` | `1` | [tradingagents/default_config.py:133](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L133) |
| `max_risk_discuss_rounds` | `1` | [tradingagents/default_config.py:134](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L134) |
| `max_recur_limit` | `100` | [tradingagents/default_config.py:135](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L135) |
| `max_tool_rounds` | `20` | [tradingagents/default_config.py:137](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L137) |
| `news_article_limit` | `20` | [tradingagents/default_config.py:141](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L141) |
| `global_news_article_limit` | `10` | [tradingagents/default_config.py:142](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L142) |
| `global_news_lookback_days` | `7` | [tradingagents/default_config.py:143](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L143) |
| `global_news_queries` | `['Federal Reserve interest rates inflation', 'S&P 500 earnings GDP economic outlook', 'geopolitical risk trade war sanctions', 'ECB Bank of England BOJ central bank policy', 'oil commodities supply chain energy']` | [tradingagents/default_config.py:146](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L146) |
| `data_vendors` | `{'core_stock_apis': 'yfinance', 'technical_indicators': 'yfinance', 'fundamental_data': 'sec_edgar,yfinance', 'news_data': 'yfinance', 'macro_data': 'fred', 'prediction_markets': 'polymarket'}` | [tradingagents/default_config.py:158](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L158) |
| `tool_vendors` | `{}` | [tradingagents/default_config.py:169](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L169) |
| `holding_period_days` | `5` | [tradingagents/default_config.py:180](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L180) |
| `benchmark_ticker` | `None` | [tradingagents/default_config.py:181](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L181) |
| `benchmark_map` | `{'.NS': '^NSEI', '.BO': '^BSESN', '.T': '^N225', '.TW': '^TWII', '.TWO': '^TWII', '.KS': '^KS11', '.KQ': '^KQ11', '.HK': '^HSI', '.SI': '^STI', '.L': '^FTSE', '.DE': '^GDAXI', '.PA': '^FCHI', '.AS': '^AEX', '.SW': '^SSMI', '.MI': 'FTSEMIB.MI', '.TO': '^GSPTSE', '.AX': '^AXJO', '.SS': '000001.SS', '.SZ': '399001.SZ', '.SA': '^BVSP', '': 'SPY'}` | [tradingagents/default_config.py:182](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L182) |

Environment-to-config mapping: `TRADINGAGENTS_LLM_PROVIDER` -> `llm_provider`, `TRADINGAGENTS_DEEP_THINK_LLM` -> `deep_think_llm`, `TRADINGAGENTS_QUICK_THINK_LLM` -> `quick_think_llm`, `TRADINGAGENTS_DEEP_THINK_PROVIDER` -> `deep_think_provider`, `TRADINGAGENTS_QUICK_THINK_PROVIDER` -> `quick_think_provider`, `TRADINGAGENTS_DEEP_THINK_BACKEND_URL` -> `deep_think_backend_url`, `TRADINGAGENTS_QUICK_THINK_BACKEND_URL` -> `quick_think_backend_url`, `TRADINGAGENTS_LLM_BACKEND_URL` -> `backend_url`, `TRADINGAGENTS_OUTPUT_LANGUAGE` -> `output_language`, `TRADINGAGENTS_MAX_DEBATE_ROUNDS` -> `max_debate_rounds`, `TRADINGAGENTS_MAX_RISK_ROUNDS` -> `max_risk_discuss_rounds`, `TRADINGAGENTS_MAX_TOOL_ROUNDS` -> `max_tool_rounds`, `TRADINGAGENTS_CHECKPOINT_ENABLED` -> `checkpoint_enabled`, `TRADINGAGENTS_BENCHMARK_TICKER` -> `benchmark_ticker`, `TRADINGAGENTS_TEMPERATURE` -> `temperature`, `TRADINGAGENTS_LLM_MAX_RETRIES` -> `llm_max_retries`, `TRADINGAGENTS_MAX_TOKENS` -> `max_tokens`, `TRADINGAGENTS_GOOGLE_THINKING_LEVEL` -> `google_thinking_level`, `TRADINGAGENTS_OPENAI_REASONING_EFFORT` -> `openai_reasoning_effort`, `TRADINGAGENTS_ANTHROPIC_EFFORT` -> `anthropic_effort`

Results/cache/memory path envs source default expressions mein alag read hote hain. `.env` followed by `.env.enterprise` package import par load hote hain; existing environment override nahi hota. User's real env/keys is review mein print/read nahi kiye gaye. `.env.example` aur `.env.enterprise.example` placeholders/configuration documentation hain, valid shipped credentials nahi.

Dependencies actual pyproject se: `cryptography>=42.0`, `langchain-core>=1.6.5`, `langchain-anthropic>=1.7.4`, `langchain-google-genai>=4.4.0`, `langchain-openai>=1.6.6`, `langgraph>=1.2.12`, `langgraph-checkpoint-sqlite>=3.1.1`, `markdown-it-py>=4.0`, `packaging>=24.0`, `pandas>=3.0.6`, `python-dotenv>=1.0.0`, `pytz>=2025.2`, `questionary>=2.1.0`, `requests>=2.32.4`, `rich>=14.0.0`, `typer>=0.21.0`, `stockstats>=0.6.5`, `typing-extensions>=4.14.0`, `yfinance>=1.7.0`. Dev extra Ruff/Pytest/Pytest-subtests, Bedrock extra langchain-aws add karta hai. `requirements.txt` only `.` install karta hai, dependency authority pyproject hai. Source minimum-version constraints installed compatibility ya external model availability certify nahi karte.

Sources: [tradingagents/default_config.py:1-208](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/default_config.py#L1-L208), [tradingagents/__init__.py:5-13](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/__init__.py#L5-L13), [pyproject.toml:12-45](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/pyproject.toml#L12-L45), [requirements.txt:1-3](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/requirements.txt#L1-L3). Full metadata: [project-metadata.json](tradingagent-evidence/project-metadata.json).

## 7. CLI, entry points aur saved preferences

Installed `tradingagents` console entry `cli.main:app` hai. Bare invocation analysis callback chalati hai; named commands `backtest`, `login`, `logout` hain. `main.py` example graph construct karke NVDA dated run immediately invoke karta hai; is review mein isko execute nahi kiya gaya, kyunki live data/model calls ho sakti hain.

| Entry function | Parameter | Declared flags | Default/required expression | Source |
| --- | --- | --- | --- | --- |
| analyze | `checkpoint` | `--checkpoint/--no-checkpoint` | `None` | [cli/main.py:39](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L39) |
| analyze | `clear_checkpoints` | `--clear-checkpoints` | `False` | [cli/main.py:45](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L45) |
| analyze | `portfolio` | `--portfolio` | `None` | [cli/main.py:50](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L50) |
| analyze | `ticker` | `--ticker` | `None` | [cli/main.py:56](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L56) |
| analyze | `date` | `--date` | `None` | [cli/main.py:57](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L57) |
| analyze | `analysts` | `--analysts` | `None` | [cli/main.py:58](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L58) |
| analyze | `save` | `--save/--no-save` | `None` | [cli/main.py:61](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L61) |
| analyze | `show` | `--show/--no-show` | `None` | [cli/main.py:64](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L64) |
| analyze | `html` | `--html/--no-html` | `None` | [cli/main.py:67](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L67) |
| backtest | `tickers` | positional | `...` | [cli/main.py:109](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L109) |
| backtest | `start` | `--start` | `...` | [cli/main.py:110](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L110) |
| backtest | `end` | `--end` | `...` | [cli/main.py:111](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L111) |
| backtest | `every` | `--every` | `7` | [cli/main.py:112](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L112) |
| backtest | `analysts` | `--analysts` | `None` | [cli/main.py:113](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L113) |
| backtest | `asset_type` | `--asset-type` | `'stock'` | [cli/main.py:116](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L116) |
| backtest | `portfolio` | `--portfolio` | `None` | [cli/main.py:117](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L117) |
| backtest | `run_id` | `--run-id` | `None` | [cli/main.py:120](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L120) |

Inventory source Typer arguments/options ka hai, full CLI --help runtime capture nahi (Typer/LangChain unavailable here). Callback flags apni questions answer karte hain; provider/models/depth/language envs bhi set hon to unattended flow possible hai. Ticker/date missing aur stdin non-terminal ho to interactive defaults guess karna safe behavior nahi maana gaya; tests headless/console cases cover karte hain. Invalid portfolio/setup errors CLI exit1 kar sakte hain. `--clear-checkpoints` saved files delete karne ka explicit user command hai; analysis mein nahi chalaya.

`cli_prefs.json` stable selections store karta hai: language, analysts, depth, provider, quick/deep models, backend URL. Ticker/date deliberately remembered nahi. Saved choices prompts prefill karte hain; silently skip nahi. Stale catalog choices drop ho sakti hain. See [cli/main.py:36-185](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/main.py#L36-L185), [cli/prefs.py:1-65](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/prefs.py#L1-L65), [tests/test_cli_headless.py:1-25](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_cli_headless.py#L1-L25).

Terminal startup update check interactive TTY+non-CI runs mein background daily release/announcement fetch schedule kar sakta hai. URLs GitHub latest release aur api.tauric.ai announcements hain;2second timeout,24h cache, `TRADINGAGENTS_NO_UPDATE_CHECK=1` opt-out. Current run cache se notice read karti hai, network answer next run par show ho sakta hai. Yeh auto software install/update nahi hai. Source: [cli/updates.py:1-46](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/updates.py#L1-L46).

## 8. Portfolio input: context, ledger nahi

`Position` has ticker, signed quantity, optional average_price. `PortfolioContext` has optional cash/currency and positions; non-finite numbers disallowed. Negative quantity short units represent kar sakti hai. Canonical alias matching analyze kiye instrument ke holdings ko prompt mein pehle show karti hai; other positions aur cash follow karte hain. Missing context, supplied flat book, held position distinct states hain; missing context ko fabricated zero position nahi banaya jaana chahiye.

Fingerprint SHA256 serialized book ke first12hex se checkpoint identity mein contribute karta hai. `load_portfolio` JSON/file/schema error ko early ValueError banata hai. It is caller-supplied standing book, broker synchronized holdings/cash ledger nahi; no fills/proceeds update loop. Research Bull/Bear ko portfolio se anchor karne ke bajay decision-side agents context read karte hain. Sources: [tradingagents/portfolio.py:1-81](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/portfolio.py#L1-L81), [tests/test_portfolio_context.py:1-49](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_portfolio_context.py#L1-L49).

## 9. Decision memory aur deferred reflection

Markdown memory stores `[date | ticker | rating | pending]`, DECISION body aur `<!-- ENTRY_END -->` delimiter. Same ticker/date duplicate record guard hai, pending/settled dono count hote hain. Settlement return/reflection add karke file atomically replace karti hai; naam “append-only” hone ke bawajood settled entry rewrite hoti hai. `locked` cross-thread/process file lock, separate settlement lock duplicate reflection cost avoid karte hain. Rotation optional cap oldest resolved decisions prune karta hai; pending entries retain hote hain.

Past-context default up to5same-ticker full lessons +3cross-ticker reflections most recent decision date se select karta hai. `as_of` supplied ho to resolved-known-by date <=analysis date required; unresolved entries and legacy entries lacking that date historical lesson context mein nahi aati. No as_of disables temporal filter. Reflection new remote LLM call hai, weight training/update nahi; short plain-prose lesson future PM prompt context ban sakta hai.

Settlement prices first completed daily close strictly after decision date se start karti hain. h=5holding days default: exit stock series indexh, requiring >h positive completed closes. Current market day's still-forming bar discarded hai. Stock and benchmark calendars separate ho sakte hain; benchmark last available close at both endpoint dates use hota hai, but benchmark must trade through exit. Missing full window stays pending; long closures ke liye fetch horizon todaytak expand ho sakti hai. Source raw return `(exit-entry)/entry`, benchmark return analogous, alpha `raw-benchmark`; this is not direction-adjusted strategy P&L or multi-currency portfolio return.

Explicit benchmark override wins, otherwise exchange suffix map: e.g .NS→^NSEI, .BO→^BSESN, .T→^N225; unknown/no suffix SPY fallback. Each return own currency mein percent hai; FX conversion/hedging engine nahi. Outcomes/reflections date recorded hone ke baad eligible future lessons ban sakte hain. Price/reflection errors logged and remain pending. `settle_all_pending` all tickers handle kar sakta hai, only current symbol tak limited nahi.

Sources: [tradingagents/memory/log.py:12-131](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/memory/log.py#L12-L131), [tradingagents/memory/log.py:138-309](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/memory/log.py#L138-L309), [tradingagents/memory/settlement.py:16-118](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/memory/settlement.py#L16-L118), [tradingagents/memory/settlement.py:129-192](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/memory/settlement.py#L129-L192), [tradingagents/memory/reflection.py:6-63](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/memory/reflection.py#L6-L63), [tradingagents/dataflows/files.py:14-88](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/files.py#L14-L88).

## 10. Backtest ka exact meaning aur limits

`iter_grid` canonical YYYY-MM-DD inclusive calendar grid banata hai, positive every_n_days require karta hai, future end today par cap karta hai. Programmatic spacing default1calendar day, CLI default7calendar days; market-calendar-only selection nahi. Tickers×dates cells deduplicate hote hain. Separate `<results_dir>/backtest/<run_id>` directory and trading_memory.md live log ko flood hone se bachate hain. Existing run_id safe path component validate hota hai; own log ke already-recorded cells skip hote hain, interrupted grid can continue. Each cell propagate failure collect hoti hai; end settlement pass last cells ko settle karne ki koshish karti hai.

Summarizer settled entries by five-tier rating groups karta hai. Buy/Overweight direction+1, Sell/Underweight−1; hit when alpha*direction>0, zero-alpha hit nahi. Hold ka directional hit-rate None. Mean alpha arithmetic average hai, portfolio profit nahi; underlying log alpha1decimal percentage tak rounded hai, higher precision claim nahi. REVIEW entries unscored hain; unfinished windows pending separately shown. Output one stochastic sampling per cell aur non-archived text feeds ko indicative/non-repeatable caveat deta hai.

Most important: no order quantities, fill price/cash ledger, fees, spread/slippage, transaction matching or evolving positions in this backtest. Optional portfolio same standing snapshot every cell hai. README simulated-exchange wording se executable portfolio backtester invent nahi kiya gaya. Sources: [tradingagents/backtest.py:1-55](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/backtest.py#L1-L55), [tradingagents/backtest.py:66-128](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/backtest.py#L66-L128), [tradingagents/backtest.py:143-236](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/backtest.py#L143-L236), [tests/test_backtest.py:1-15](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/test_backtest.py#L1-L15).

## 11. Outputs aur local file lifecycle

| Artifact | Actual role |
| --- | --- |
| `~/.tradingagents/logs` default results_dir | Run JSON/log/report roots; env override available |
| `<results_dir>/<safe ticker>/TradingAgentsStrategy_logs/full_states_log_<date>.json` | Final reports/debate histories/settings; same date path overwritten |
| `<results_dir>/<ticker>/<date>/message_tool.log` and reports/ | CLI message/tool recording and incremental section files |
| `<results_dir>/reports/<ticker>_<timestamp>/` | Default complete-report export directory |
| `complete_report.md`, `complete_report.html` | Shared writer's full report; HTML optional |
| `1_analysts`, `2_research`, `3_trading`, `4_risk`, `5_portfolio` | Per-role markdown output sections |
| `~/.tradingagents/memory/trading_memory.md` | Pending/settled decisions/reflections; configurable |
| `<cache>/checkpoints/<safe ticker>.db` | Optional LangGraph SQLite state; thread signature matters |
| `~/.tradingagents/cli_prefs.json` | Interactive stable defaults, not ticker/date |
| `~/.tradingagents/update_check.json` | Release/announcement notice cache |
| Data cache directory | Vendor OHLCV/statement/cache artifacts, not independent historical archive |

`write_report_tree` CLI and API parity provides, header includes ticker/date/version/run settings and memory note. Empty sections skipped; own stale section files removed on reuse; unrelated user files retained. HTML is one standalone page with inline CSS/logo; raw model HTML and images disabled, metadata escaped, restrictive CSP and no injected script/external asset fetch by renderer. Reports can contain portfolio, data and model text; these outputs are not an encrypted private vault.

Sources: [tradingagents/reporting.py:20-136](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/reporting.py#L20-L136), [tradingagents/report_html.py:1-14](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/report_html.py#L1-L14), [tradingagents/report_html.py:187-208](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/report_html.py#L187-L208), [tradingagents/graph/trading_graph.py:255-291](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L255-L291), [tradingagents/graph/trading_graph.py:438-476](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L438-L476), [cli/run.py:132-179](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/run.py#L132-L179), [cli/run.py:426-462](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/cli/run.py#L426-L462).

## 12. Packaging, Docker, CI aur security boundaries

Setuptools packages tradingagents* and cli*, CLI static files and SVG package assets. `pip install .` or requirements file installs declared dependencies; none were installed here. Bedrock support optional extra. Docker Python3.13slim builder installs package into venv, copies it into final non-root appuser image; entrypoint tradingagents. Compose persistent ~/.tradingagents volume and optional Ollama service/profile define karta hai. Ollama profile sets model provider and internal endpoint; pulling/configuring an actual model still external runtime requirement hai. Docker/image/LLM/server run nahi kiye gaye.

CI configured Python3.11–3.14 and extra America/New_York case, install smoke, Ruff. Pytest default explicitly excludes integration marker. Shared suite fixtures isolate user paths/preferences/config, block Python sockets and curl_cffi requests for non-integration tests, and insert placeholder keys. Source fixture declarations testisolation intent show karti hain; all tests pass hue yeh yahan claim nahi. Release workflow tag/version matches, builds wheel/sdist, clean-installs wheel, checks bundled asset, uploads release files; actual release provenance inspect nahi hua.

Source safeguards include path-component validation, cache temp+replace, file locks, secret scrubbing in selected HTTP exception paths, HTML rendering restrictions, and structured rating validation. None is a universal prompt-injection guard, portfolio risk cap, encrypted-at-rest store, API licensing guarantee or broker approval gate. Remote model sees selected prompt/tool/report/history data; optional Jev screens social text via an additional service. Own remote LLM/provider choice does not turn all market-data networking off.

Sources: [pyproject.toml:47-76](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/pyproject.toml#L47-L76), [Dockerfile:1-30](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/Dockerfile#L1-L30), [docker-compose.yml:1-36](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/docker-compose.yml#L1-L36), [.github/workflows/ci.yml:1-67](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/.github/workflows/ci.yml#L1-L67), [.github/workflows/release-assets.yml:1-59](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/.github/workflows/release-assets.yml#L1-L59), [tests/conftest.py:1-135](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tests/conftest.py#L1-L135).

## 13. Verification, coverage aur explicit unknowns

Performed: pinned HEAD/clean tracked-source check; REA archive hash+all213payload match; all184Python source AST parse; manifest/default/CLI/tool inventories; independent source reading of graph, agents, vendors, LLM auth, memory/backtest/portfolio/reports/CLI/deploy. **54offline tests passed in2.00seconds** from4unmodified upstream test files: symbol normalization, safe ticker path validation, default environment coercion, query-key exception scrubbing.

This isolated subset imported actual checkout source, used a local network-blocking fixture, blank local dotenv shadow files and own app-state paths. Original broad conftest was bypassed because it pulls CLI/LangChain stack unavailable on host. No fake LangChain/LangGraph dependency stubs were used. Full suite/graph/model integration not run; absent dependencies included langchain_core, langgraph, typer, stockstats and pytest_subtests. Existing yfinance/pandas/requests availability did not mean complete installed environment.

Evidence: [test log](tradingagent-evidence/offline-tests.txt), [source-copy hashes and command](tradingagent-evidence/offline-test-manifest.json), [test runner](tradingagent-evidence/run-offline-tests.py), [AST/source inventory](tradingagent-evidence/inventory.json), [final validation](tradingagent-evidence/document-validation.json).

Coverage checklist: all root areas and production Python file inventory; every agent team and graph transitions; structured outputs/fallbacks; tools/vendor chains; point-in-time dates and gaps; model tiers/auth; config/env; portfolio; memory/reflection/outcomes; backtest metrics; CLI; report formats; filesystem/network boundaries; package/Docker/CI; executable/source limits. Detailed function/class/CLI inventories preserve lower-level navigation.

Not established: full dependency-installed test pass; live API/model entitlement/output; cross-platform checkpoint/concurrency/locks under load; paper/live order execution; realized profitable strategy; archived as-known text/adjusted price perfection; hosted Trading-R1 internals; original private prompts/authorship. Dates filtered in code do not make historical feeds complete or LLM factual claims guaranteed. This documentation is complete within stated source-analysis scope, not an all-line security audit or operational certification.

## 14. Full tracked file list aur evidence

```text
.dockerignore
.env.enterprise.example
.env.example
.github/ISSUE_TEMPLATE/bug-report.yml
.github/ISSUE_TEMPLATE/config.yml
.github/ISSUE_TEMPLATE/data-issue.yml
.github/ISSUE_TEMPLATE/feature-request.yml
.github/workflows/ci.yml
.github/workflows/release-assets.yml
.gitignore
CHANGELOG.md
Dockerfile
LICENSE
README.md
assets/TauricResearch.png
assets/analyst.png
assets/cli/cli_init.png
assets/cli/cli_news.png
assets/cli/cli_technical.png
assets/cli/cli_transaction.png
assets/researcher.png
assets/risk.png
assets/schema.png
assets/trader.png
cli/__init__.py
cli/display.py
cli/main.py
cli/models.py
cli/prefs.py
cli/prompts.py
cli/run.py
cli/selections.py
cli/static/welcome.txt
cli/stats_handler.py
cli/updates.py
docker-compose.yml
main.py
pyproject.toml
requirements.txt
tests/__init__.py
tests/conftest.py
tests/test_alpha_vantage_hardening.py
tests/test_analyst_execution.py
tests/test_anthropic_effort.py
tests/test_api_key_env.py
tests/test_azure_client.py
tests/test_backtest.py
tests/test_bedrock_provider.py
tests/test_cache_writes.py
tests/test_capabilities.py
tests/test_chatgpt_auth.py
tests/test_chatgpt_provider.py
tests/test_checkpoint_lifecycle.py
tests/test_checkpoint_resume.py
tests/test_cli_commands.py
tests/test_cli_config_precedence.py
tests/test_cli_display.py
tests/test_cli_env_skip.py
tests/test_cli_headless.py
tests/test_cli_memory_log.py
tests/test_cli_no_console.py
tests/test_cli_prefs.py
tests/test_cli_symbol_handling.py
tests/test_cli_updates.py
tests/test_crypto_asset_mode.py
tests/test_dataflows_config.py
tests/test_date_boundaries.py
tests/test_debate_opening.py
tests/test_deepseek_reasoning.py
tests/test_env_overrides.py
tests/test_fred.py
tests/test_fundamentals_lookahead.py
tests/test_fundamentals_units.py
tests/test_get_scrubbed.py
tests/test_google_api_key.py
tests/test_google_thinking_level.py
tests/test_graph_end_to_end.py
tests/test_i18n_coverage.py
tests/test_instrument_identity.py
tests/test_layering.py
tests/test_llm_max_retries.py
tests/test_llm_max_tokens.py
tests/test_memory_log.py
tests/test_memory_pointintime.py
tests/test_minimax.py
tests/test_model_validation.py
tests/test_news_analyst_prompt.py
tests/test_news_lookahead.py
tests/test_no_data_handling.py
tests/test_ohlcv_cache_freshness.py
tests/test_ohlcv_date_column.py
tests/test_ohlcv_latest_bar.py
tests/test_ollama_base_url.py
tests/test_openai_compatible_provider.py
tests/test_openai_reasoning_effort.py
tests/test_openai_responses_base_url.py
tests/test_openrouter_model_select.py
tests/test_polymarket.py
tests/test_portfolio_context.py
tests/test_post_screen.py
tests/test_prompt_integrity.py
tests/test_provider_registry.py
tests/test_rating_integrity.py
tests/test_reddit_fallback.py
tests/test_report_html.py
tests/test_reporting.py
tests/test_risk_router_path_map.py
tests/test_safe_ticker_component.py
tests/test_sec_edgar.py
tests/test_signal_processing.py
tests/test_social_lookahead.py
tests/test_statement_knowledge_time.py
tests/test_stocktwits_resilience.py
tests/test_structured_agent_prompts.py
tests/test_structured_agents.py
tests/test_suite_isolation.py
tests/test_symbol_normalization_paths.py
tests/test_symbols.py
tests/test_temperature_config.py
tests/test_ticker_symbol_handling.py
tests/test_tier_providers.py
tests/test_tool_date_enforcement.py
tests/test_undated_tools_as_of.py
tests/test_vendor_errors.py
tests/test_vendor_routing.py
tests/test_version.py
tests/test_yahoo_rate_limit.py
tests/test_yahoo_snapshot.py
tests/test_yfinance_stale_ohlcv_guard.py
tradingagents/__init__.py
tradingagents/agents/__init__.py
tradingagents/agents/analysts/__init__.py
tradingagents/agents/analysts/fundamentals_analyst.py
tradingagents/agents/analysts/market_analyst.py
tradingagents/agents/analysts/news_analyst.py
tradingagents/agents/analysts/sentiment_analyst.py
tradingagents/agents/analysts/turn.py
tradingagents/agents/context.py
tradingagents/agents/managers/__init__.py
tradingagents/agents/managers/portfolio_manager.py
tradingagents/agents/managers/research_manager.py
tradingagents/agents/post_screen.py
tradingagents/agents/rating.py
tradingagents/agents/researchers/__init__.py
tradingagents/agents/researchers/bear_researcher.py
tradingagents/agents/researchers/bull_researcher.py
tradingagents/agents/risk_mgmt/__init__.py
tradingagents/agents/risk_mgmt/aggressive_debator.py
tradingagents/agents/risk_mgmt/conservative_debator.py
tradingagents/agents/risk_mgmt/neutral_debator.py
tradingagents/agents/schemas.py
tradingagents/agents/state.py
tradingagents/agents/structured.py
tradingagents/agents/tools.py
tradingagents/agents/trader/__init__.py
tradingagents/agents/trader/trader.py
tradingagents/assets/tauric-logo.svg
tradingagents/backtest.py
tradingagents/dataflows/__init__.py
tradingagents/dataflows/config.py
tradingagents/dataflows/date_window.py
tradingagents/dataflows/errors.py
tradingagents/dataflows/files.py
tradingagents/dataflows/net.py
tradingagents/dataflows/router.py
tradingagents/dataflows/symbols.py
tradingagents/dataflows/vendors/__init__.py
tradingagents/dataflows/vendors/alpha_vantage/__init__.py
tradingagents/dataflows/vendors/alpha_vantage/common.py
tradingagents/dataflows/vendors/alpha_vantage/fundamentals.py
tradingagents/dataflows/vendors/alpha_vantage/indicator.py
tradingagents/dataflows/vendors/alpha_vantage/news.py
tradingagents/dataflows/vendors/alpha_vantage/stock.py
tradingagents/dataflows/vendors/fred.py
tradingagents/dataflows/vendors/polymarket.py
tradingagents/dataflows/vendors/reddit.py
tradingagents/dataflows/vendors/sec_edgar.py
tradingagents/dataflows/vendors/stocktwits.py
tradingagents/dataflows/vendors/yahoo/__init__.py
tradingagents/dataflows/vendors/yahoo/common.py
tradingagents/dataflows/vendors/yahoo/fundamentals.py
tradingagents/dataflows/vendors/yahoo/market.py
tradingagents/dataflows/vendors/yahoo/news.py
tradingagents/dataflows/vendors/yahoo/ohlcv.py
tradingagents/dataflows/vendors/yahoo/snapshot.py
tradingagents/default_config.py
tradingagents/graph/__init__.py
tradingagents/graph/analyst_execution.py
tradingagents/graph/checkpointer.py
tradingagents/graph/conditional_logic.py
tradingagents/graph/propagation.py
tradingagents/graph/setup.py
tradingagents/graph/trading_graph.py
tradingagents/llm_clients/__init__.py
tradingagents/llm_clients/anthropic_client.py
tradingagents/llm_clients/api_key_env.py
tradingagents/llm_clients/azure_client.py
tradingagents/llm_clients/base_client.py
tradingagents/llm_clients/bedrock_client.py
tradingagents/llm_clients/capabilities.py
tradingagents/llm_clients/chatgpt_auth.py
tradingagents/llm_clients/factory.py
tradingagents/llm_clients/google_client.py
tradingagents/llm_clients/model_catalog.py
tradingagents/llm_clients/openai_client.py
tradingagents/llm_clients/validators.py
tradingagents/memory/__init__.py
tradingagents/memory/log.py
tradingagents/memory/reflection.py
tradingagents/memory/settlement.py
tradingagents/portfolio.py
tradingagents/report_html.py
tradingagents/reporting.py
```

Saved reviewer notes: [graph](tradingagent-evidence/graph-notes.md), [data/LLM](tradingagent-evidence/data-llm-notes.md). Additional inventories: [CLI options](tradingagent-evidence/cli-option-catalog.json), [default config expressions](tradingagent-evidence/default-config-catalog.json), [tool catalog](tradingagent-evidence/tool-catalog.json), [source references validation](tradingagent-evidence/source-reference-check.json). REA output, archive, Git identity checks and tests live under tradingagent-evidence; these review artifacts original repository features nahi hain.
