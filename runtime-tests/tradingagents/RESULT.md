# TradingAgents local installed runtime: PASS

Revision: `9fa1196fffbcfd9de5146d2dd2869df84ab99838` (version 0.7.1). Repository clean before and after; no tracked changes.

Python 3.13.5, fresh isolated venv. Installed a normal wheel and all declared dependencies. Dependency integrity: `pip check` exit 0. Final runtime run: **21 passed, 0 failed, 0 skipped**, 2 warnings, 21.13 seconds. JUnit and full logs retained. All package imports resolve to this venv's site-packages, not a copied source implementation.

Six real runtime checks verify installed package origin; construct OpenAI, Anthropic, Google and generic local OpenAI-compatible SDK clients with dummy credentials; bind real tool and structured-output schemas; compile the full graph using real provider objects. No model generation calls occur in those checks.

Fifteen repository E2E cases execute the actual installed LangGraph: all four analysts, tool nodes/vendor router, research/risk debates, managers, trader, final decision parsing and persistence. They cover free-text/structured responses, checkpoint interruption/resume, reused graphs, parallel analysts, streaming/config isolation, tool round limits, and memory settlement. LLM output, vendor data, instrument identity and social feeds are deterministic fixtures. These are meaningful local integration checks, not evidence of live LLM or data service quality.

Network access is denied during tests through Python socket and curl_cffi guards. dotenv discovery/loading are replaced before package import, so private .env files are not read. Results/cache/memory paths stay in artifacts. Live paid LLM calls, live market data, broker execution and optional Bedrock were not exercised.

The two warnings are the repository model registry not recognizing the chosen Anthropic and Google model IDs; construction and schema/tool binding still pass. Initial harness attempts revealed missing pytest marker registration and a missing required local-provider base_url; both were corrected only in artifacts. Earlier logs retained for transparency.

Reproduce with `commands.ps1` (initial setup/install commands are documented there). Exact dependency versions in `versions.txt`, installed graph nodes in `graph-nodes.json`, persisted synthetic outputs in `pytest-data`.

Latest verified shared five-hour usage: 89% consumed / 11% remaining. Work complete; no further tests needed.
