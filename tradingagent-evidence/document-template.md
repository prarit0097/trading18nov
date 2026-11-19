# TradingAgents — source aur REA evidence se detailed analysis

Completed: 16 November 2026 (Asia/Kolkata). Language: Roman Hindi / Hinglish.

Yeh document actual inspected source ko explain karta hai. Isme naya trading feature, private authoring story, invented return, recommendation ya source fix add nahi kiya gaya. Source observations aur runtime-unverified claims alag hain. Original repository unchanged hai.

## 1. Identity, scope aur construction

Requested repository: https://github.com/TauricResearch/TradingAgents

Pinned commit: `9fa1196fffbcfd9de5146d2dd2869df84ab99838`. Git timestamp `2026-11-04T02:13:55-08:00`; subject `announce Trading-R1 official release`. Local source: `E:\coding\code\Trade\TradingAgents`. Clone shallow hai; full historical authorship/development sequence inspect nahi hui.

Package version `0.7.1` `tradingagents/__init__.py` se aati hai; setuptools dynamic version wahi read karta hai. Python requirement `>=3.11`. Apache2.0 license supplied hai. Python runtime used for verification3.13.5 on Windows. README ka Trading-R1 early-access product announcement is source package ka independently verified hosted implementation nahi hai.

Construction: Python modules + LangGraph state orchestration + LangChain model/tool clients + data-vendor adapters + typed Pydantic decisions + persisted Markdown memory + optional SQLite checkpoints + Typer/Rich terminal + Markdown/HTML reports. Separately trained per-role models/weights is tree mein establish nahi hote. Roles mostly prompts aur graph nodes hain. User-supplied market/portfolio input aur remote model outputs se decision reports bante hain; this graph is not a demonstrated broker execution engine.

Sources: [[tradingagents/__init__.py:1-13]], [[pyproject.toml:1-65]], [[main.py:1-16]], [[LICENSE:1-8]].

## 2. REA evidence aur independent archive check

Existing REA6.7.0 CLI used: `rea inspect-artifact E:/coding/code/Trade/tradingagent-evidence/source.zip --format json --full-output`. Input pinned Git commit ka locally created ZIP hai. REA static inventory ko runtime execution/decompilation/profitability claim nahi banaya gaya. Ordinary Python architecture source reading se established hai.

__REA__

Independent Git-blob comparison: all213tracked paths matched;17payloads byte-exact,196sirf CRLF/LF normalization ke baad matched; zero unmatched. ZIP comment inspected commit se match hai. Reported `complete-within-substeps` ZIP inventory tak limited hai; central-directory ke bahar non-entry bytes coverage mein nahi. Released executable ya private hosted product ka inventory nahi hua.

Evidence: [raw REA result](tradingagent-evidence/rea-artifact.json), [summary/hash/payload verification](tradingagent-evidence/rea-summary.json), [archive](tradingagent-evidence/source.zip), [verifier](tradingagent-evidence/verify-archive.py).

## 3. Repository map aur counts

__ROOTS__

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

__GRAPH__

## 5. Data contracts, vendors aur model clients

__DATA_LLM__

## 6. Configuration: complete built-in key index

Neeche values source ke pre-environment default expressions hain, machine ke actual credentials/config values nahi. `build_default_config()` import-time DEFAULT_CONFIG ke liye environment fold karta hai; function dobara call karne par current environment reread hota hai. Python callers explicit keys override kar sakte hain. `DEFAULT_CONFIG.copy()` shallow dict copy hai; run-local dataflows config helpers nested dicts ke isolation/merge rules independently implement karte hain.

__DEFAULTS__

Environment-to-config mapping: __ENV_KEYS__

Results/cache/memory path envs source default expressions mein alag read hote hain. `.env` followed by `.env.enterprise` package import par load hote hain; existing environment override nahi hota. User's real env/keys is review mein print/read nahi kiye gaye. `.env.example` aur `.env.enterprise.example` placeholders/configuration documentation hain, valid shipped credentials nahi.

Dependencies actual pyproject se: __DEPENDENCIES__. Dev extra Ruff/Pytest/Pytest-subtests, Bedrock extra langchain-aws add karta hai. `requirements.txt` only `.` install karta hai, dependency authority pyproject hai. Source minimum-version constraints installed compatibility ya external model availability certify nahi karte.

Sources: [[tradingagents/default_config.py:1-208]], [[tradingagents/__init__.py:5-13]], [[pyproject.toml:12-45]], [[requirements.txt:1-3]]. Full metadata: [project-metadata.json](tradingagent-evidence/project-metadata.json).

## 7. CLI, entry points aur saved preferences

Installed `tradingagents` console entry `cli.main:app` hai. Bare invocation analysis callback chalati hai; named commands `backtest`, `login`, `logout` hain. `main.py` example graph construct karke NVDA dated run immediately invoke karta hai; is review mein isko execute nahi kiya gaya, kyunki live data/model calls ho sakti hain.

__CLI__

Inventory source Typer arguments/options ka hai, full CLI --help runtime capture nahi (Typer/LangChain unavailable here). Callback flags apni questions answer karte hain; provider/models/depth/language envs bhi set hon to unattended flow possible hai. Ticker/date missing aur stdin non-terminal ho to interactive defaults guess karna safe behavior nahi maana gaya; tests headless/console cases cover karte hain. Invalid portfolio/setup errors CLI exit1 kar sakte hain. `--clear-checkpoints` saved files delete karne ka explicit user command hai; analysis mein nahi chalaya.

`cli_prefs.json` stable selections store karta hai: language, analysts, depth, provider, quick/deep models, backend URL. Ticker/date deliberately remembered nahi. Saved choices prompts prefill karte hain; silently skip nahi. Stale catalog choices drop ho sakti hain. See [[cli/main.py:36-185]], [[cli/prefs.py:1-65]], [[tests/test_cli_headless.py:1-25]].

Terminal startup update check interactive TTY+non-CI runs mein background daily release/announcement fetch schedule kar sakta hai. URLs GitHub latest release aur api.tauric.ai announcements hain;2second timeout,24h cache, `TRADINGAGENTS_NO_UPDATE_CHECK=1` opt-out. Current run cache se notice read karti hai, network answer next run par show ho sakta hai. Yeh auto software install/update nahi hai. Source: [[cli/updates.py:1-46]].

## 8. Portfolio input: context, ledger nahi

`Position` has ticker, signed quantity, optional average_price. `PortfolioContext` has optional cash/currency and positions; non-finite numbers disallowed. Negative quantity short units represent kar sakti hai. Canonical alias matching analyze kiye instrument ke holdings ko prompt mein pehle show karti hai; other positions aur cash follow karte hain. Missing context, supplied flat book, held position distinct states hain; missing context ko fabricated zero position nahi banaya jaana chahiye.

Fingerprint SHA256 serialized book ke first12hex se checkpoint identity mein contribute karta hai. `load_portfolio` JSON/file/schema error ko early ValueError banata hai. It is caller-supplied standing book, broker synchronized holdings/cash ledger nahi; no fills/proceeds update loop. Research Bull/Bear ko portfolio se anchor karne ke bajay decision-side agents context read karte hain. Sources: [[tradingagents/portfolio.py:1-81]], [[tests/test_portfolio_context.py:1-49]].

## 9. Decision memory aur deferred reflection

Markdown memory stores `[date | ticker | rating | pending]`, DECISION body aur `<!-- ENTRY_END -->` delimiter. Same ticker/date duplicate record guard hai, pending/settled dono count hote hain. Settlement return/reflection add karke file atomically replace karti hai; naam “append-only” hone ke bawajood settled entry rewrite hoti hai. `locked` cross-thread/process file lock, separate settlement lock duplicate reflection cost avoid karte hain. Rotation optional cap oldest resolved decisions prune karta hai; pending entries retain hote hain.

Past-context default up to5same-ticker full lessons +3cross-ticker reflections most recent decision date se select karta hai. `as_of` supplied ho to resolved-known-by date <=analysis date required; unresolved entries and legacy entries lacking that date historical lesson context mein nahi aati. No as_of disables temporal filter. Reflection new remote LLM call hai, weight training/update nahi; short plain-prose lesson future PM prompt context ban sakta hai.

Settlement prices first completed daily close strictly after decision date se start karti hain. h=5holding days default: exit stock series indexh, requiring >h positive completed closes. Current market day's still-forming bar discarded hai. Stock and benchmark calendars separate ho sakte hain; benchmark last available close at both endpoint dates use hota hai, but benchmark must trade through exit. Missing full window stays pending; long closures ke liye fetch horizon todaytak expand ho sakti hai. Source raw return `(exit-entry)/entry`, benchmark return analogous, alpha `raw-benchmark`; this is not direction-adjusted strategy P&L or multi-currency portfolio return.

Explicit benchmark override wins, otherwise exchange suffix map: e.g .NS→^NSEI, .BO→^BSESN, .T→^N225; unknown/no suffix SPY fallback. Each return own currency mein percent hai; FX conversion/hedging engine nahi. Outcomes/reflections date recorded hone ke baad eligible future lessons ban sakte hain. Price/reflection errors logged and remain pending. `settle_all_pending` all tickers handle kar sakta hai, only current symbol tak limited nahi.

Sources: [[tradingagents/memory/log.py:12-131]], [[tradingagents/memory/log.py:138-309]], [[tradingagents/memory/settlement.py:16-118]], [[tradingagents/memory/settlement.py:129-192]], [[tradingagents/memory/reflection.py:6-63]], [[tradingagents/dataflows/files.py:14-88]].

## 10. Backtest ka exact meaning aur limits

`iter_grid` canonical YYYY-MM-DD inclusive calendar grid banata hai, positive every_n_days require karta hai, future end today par cap karta hai. Programmatic spacing default1calendar day, CLI default7calendar days; market-calendar-only selection nahi. Tickers×dates cells deduplicate hote hain. Separate `<results_dir>/backtest/<run_id>` directory and trading_memory.md live log ko flood hone se bachate hain. Existing run_id safe path component validate hota hai; own log ke already-recorded cells skip hote hain, interrupted grid can continue. Each cell propagate failure collect hoti hai; end settlement pass last cells ko settle karne ki koshish karti hai.

Summarizer settled entries by five-tier rating groups karta hai. Buy/Overweight direction+1, Sell/Underweight−1; hit when alpha*direction>0, zero-alpha hit nahi. Hold ka directional hit-rate None. Mean alpha arithmetic average hai, portfolio profit nahi; underlying log alpha1decimal percentage tak rounded hai, higher precision claim nahi. REVIEW entries unscored hain; unfinished windows pending separately shown. Output one stochastic sampling per cell aur non-archived text feeds ko indicative/non-repeatable caveat deta hai.

Most important: no order quantities, fill price/cash ledger, fees, spread/slippage, transaction matching or evolving positions in this backtest. Optional portfolio same standing snapshot every cell hai. README simulated-exchange wording se executable portfolio backtester invent nahi kiya gaya. Sources: [[tradingagents/backtest.py:1-55]], [[tradingagents/backtest.py:66-128]], [[tradingagents/backtest.py:143-236]], [[tests/test_backtest.py:1-15]].

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

Sources: [[tradingagents/reporting.py:20-136]], [[tradingagents/report_html.py:1-14]], [[tradingagents/report_html.py:187-208]], [[tradingagents/graph/trading_graph.py:255-291]], [[tradingagents/graph/trading_graph.py:438-476]], [[cli/run.py:132-179]], [[cli/run.py:426-462]].

## 12. Packaging, Docker, CI aur security boundaries

Setuptools packages tradingagents* and cli*, CLI static files and SVG package assets. `pip install .` or requirements file installs declared dependencies; none were installed here. Bedrock support optional extra. Docker Python3.13slim builder installs package into venv, copies it into final non-root appuser image; entrypoint tradingagents. Compose persistent ~/.tradingagents volume and optional Ollama service/profile define karta hai. Ollama profile sets model provider and internal endpoint; pulling/configuring an actual model still external runtime requirement hai. Docker/image/LLM/server run nahi kiye gaye.

CI configured Python3.11–3.14 and extra America/New_York case, install smoke, Ruff. Pytest default explicitly excludes integration marker. Shared suite fixtures isolate user paths/preferences/config, block Python sockets and curl_cffi requests for non-integration tests, and insert placeholder keys. Source fixture declarations testisolation intent show karti hain; all tests pass hue yeh yahan claim nahi. Release workflow tag/version matches, builds wheel/sdist, clean-installs wheel, checks bundled asset, uploads release files; actual release provenance inspect nahi hua.

Source safeguards include path-component validation, cache temp+replace, file locks, secret scrubbing in selected HTTP exception paths, HTML rendering restrictions, and structured rating validation. None is a universal prompt-injection guard, portfolio risk cap, encrypted-at-rest store, API licensing guarantee or broker approval gate. Remote model sees selected prompt/tool/report/history data; optional Jev screens social text via an additional service. Own remote LLM/provider choice does not turn all market-data networking off.

Sources: [[pyproject.toml:47-76]], [[Dockerfile:1-30]], [[docker-compose.yml:1-36]], [[.github/workflows/ci.yml:1-67]], [[.github/workflows/release-assets.yml:1-59]], [[tests/conftest.py:1-135]].

## 13. Verification, coverage aur explicit unknowns

Performed: pinned HEAD/clean tracked-source check; REA archive hash+all213payload match; all184Python source AST parse; manifest/default/CLI/tool inventories; independent source reading of graph, agents, vendors, LLM auth, memory/backtest/portfolio/reports/CLI/deploy. **54offline tests passed in2.00seconds** from4unmodified upstream test files: symbol normalization, safe ticker path validation, default environment coercion, query-key exception scrubbing.

This isolated subset imported actual checkout source, used a local network-blocking fixture, blank local dotenv shadow files and own app-state paths. Original broad conftest was bypassed because it pulls CLI/LangChain stack unavailable on host. No fake LangChain/LangGraph dependency stubs were used. Full suite/graph/model integration not run; absent dependencies included langchain_core, langgraph, typer, stockstats and pytest_subtests. Existing yfinance/pandas/requests availability did not mean complete installed environment.

Evidence: [test log](tradingagent-evidence/offline-tests.txt), [source-copy hashes and command](tradingagent-evidence/offline-test-manifest.json), [test runner](tradingagent-evidence/run-offline-tests.py), [AST/source inventory](tradingagent-evidence/inventory.json), [final validation](tradingagent-evidence/document-validation.json).

Coverage checklist: all root areas and production Python file inventory; every agent team and graph transitions; structured outputs/fallbacks; tools/vendor chains; point-in-time dates and gaps; model tiers/auth; config/env; portfolio; memory/reflection/outcomes; backtest metrics; CLI; report formats; filesystem/network boundaries; package/Docker/CI; executable/source limits. Detailed function/class/CLI inventories preserve lower-level navigation.

Not established: full dependency-installed test pass; live API/model entitlement/output; cross-platform checkpoint/concurrency/locks under load; paper/live order execution; realized profitable strategy; archived as-known text/adjusted price perfection; hosted Trading-R1 internals; original private prompts/authorship. Dates filtered in code do not make historical feeds complete or LLM factual claims guaranteed. This documentation is complete within stated source-analysis scope, not an all-line security audit or operational certification.

## 14. Full tracked file list aur evidence

__FILES__

Saved reviewer notes: [graph](tradingagent-evidence/graph-notes.md), [data/LLM](tradingagent-evidence/data-llm-notes.md). Additional inventories: [CLI options](tradingagent-evidence/cli-option-catalog.json), [default config expressions](tradingagent-evidence/default-config-catalog.json), [tool catalog](tradingagent-evidence/tool-catalog.json), [source references validation](tradingagent-evidence/source-reference-check.json). REA output, archive, Git identity checks and tests live under tradingagent-evidence; these review artifacts original repository features nahi hain.
