# OpenBB — source aur REA evidence par detailed analysis

Document completed: 16 November 2026, Asia/Kolkata. Source snapshot captured: 15 November 2026. Language: Roman Hindi / Hinglish.

Yeh report user ke diye repository ki actual construction aur behavior explain karti hai. Nayi features, guessed author prompts, private development story, investment recommendations ya source-code fixes isme add nahi kiye gaye. Public-source observation, design interpretation aur runtime-unverified areas alag rakhe gaye hain. Original source edit nahi kiya gaya.

## 1. Repository identity aur analysis boundary

| Field | Inspected value |
| --- | --- |
| Requested repository | https://github.com/openbq-org/OpenBB |
| Pinned commit | `e43353a82815ff9ba56ad1b7ad47c32729dcf314` |
| Commit timestamp | 2026-11-13T02:14:58Z |
| Commit subject | Respect expiration when selecting option strikes (#7808) |
| Local source | `E:\coding\code\Trade\OpenBB` |
| Clone type | Shallow clone; full project history was not downloaded/read |
| Root license | Apache License 2.0, copyright2021–2026 OpenBB Inc. |
| Umbrella Python package | `openbb`5.0.0 |
| Core Python package | `openbb-core`2.0.1 |
| Declared Python constraint | `>=3.11,<4` in main/core manifests |
| Validation interpreter | Python3.13.5 on Windows |

“Kaise bani” yahan observable software composition ko refer karta hai: packages, generated SDK, models, request pipeline, adapters, user surfaces, configuration, builds aur tests. Source/commit metadata original private design discussions, author ke prompts ya per-function authorship reveal nahi karti. README ke kuch links ab bhi `OpenBB-finance/OpenBB` URL string use karte hain; report user-provided checkout ke pinned files ko cite karti hai, organizational history infer nahi karti.

Sources: [[LICENSE:1-7]], [[openbb_platform/pyproject.toml:1-12]], [[openbb_platform/core/pyproject.toml:1-12]], retained Git HEAD and inventory records.

## 2. REA ka role: kya observe hua aur kya nahi

Existing `rea-agents`6.7.0 CLI se pinned source ka ZIP inspect hua. Installed REA skill ordinary source architecture ke liye source-reading route prefer karti hai; user-requested REA ko supported artifact-inventory task ke liye use kiya gaya. Missing MCP tools ko fabricated analysis results se replace nahi kiya gaya. Koi REA engine install/upgrade nahi hua.

```text
git archive --format=zip --output=E:/coding/code/Trade/obb-evidence/OpenBB-source.zip HEAD
rea inspect-artifact E:/coding/code/Trade/obb-evidence/OpenBB-source.zip --format json --full-output
```

__REA_TABLE__

REA result ka coverage `complete-within-substeps` sirf completed ZIP-inventory substep ka scope hai. Yeh Python/Rust program execution, API authenticity, strategy profitability, production security audit ya all source algorithms ki correctness ka proof nahi. ZIP central-directory inventory non-entry bytes ko enumerate nahi karti. Input locally created source ZIP hai, original released desktop binary nahi; generic `authority` label ko released-artifact provenance ka proof nahi maana gaya.

Independent verification mein archive SHA-256 REA subject digest se match hua, ZIP comment pinned commit se match hua aur archive ke all4,143 file paths Git HEAD ke paths se match hue. Git blob hashing ke against176 files byte-exact mile;3,967 text files sirf WindowsCRLF/GitLF difference normalize karne ke baad match hue. Koi unmatched payload nahi. Archive same commit ka source preserve karti hai; line-ending difference explicit hai.

Evidence: [complete REA envelope](obb-evidence/rea-artifact.json), [REA summary and archive verification](obb-evidence/rea-summary.json), [archive verification script](obb-evidence/verify-archive.py), [source ZIP](obb-evidence/OpenBB-source.zip).

## 3. OpenBB kya hai aur kis layer ka kaam karta hai

Is snapshot ka central product Open Data Platform hai: financial/economic data sources ko typed commands ke through multiple consumers tak expose karna. Python user `obb` object use kar sakta hai; REST clients HTTP endpoints; MCP clients tools; CLI command dispatch; desktop configured backend processes manage kar sakta hai. Hosted OpenBB Workspace ko repository apni separate enterprise UI ke roop mein describe karti hai. Us hosted product ke complete frontend, account/billing systems aur private AI orchestration ki implementation is checkout se establish nahi hoti.

OpenBB ko sirf charting app, fixed ticker downloader, broker execution bot, eleven-agent skill pack ya single prediction model kehna source architecture ko misrepresent karega. Provider retrieval aur local analytics commands dono hain. Example notebooks mein strategies/LLM examples hona core ka every user ke behalf par autonomous trading karna prove nahi karta.

### Architecture map

```text
Python distributions installed in environment
    | entry-point discovery
    +--> domain routers / analytics extensions
    +--> Provider objects + fetcher mappings
    +--> OBBject/chart/output extensions
              |
      registry + model/interface maps
              |
      generated Python SDK and reference metadata
              |
Python obb call / REST route / CLI dispatch / MCP adaptation
              |
      Container + CommandRunner + context/settings
              |
    domain route -> Query -> QueryExecutor
              |
       chosen provider Fetcher
              |
 transform_query -> remote extraction/cache -> transform_data
              |
      validated canonical/provider-specific rows
              |
       OBBject(results, warnings, metadata, chart)
              |
Python conversion / HTTP JSON / terminal output / chart UI

Local analytic commands can calculate on caller-supplied data,
without taking the provider-fetcher route.
```

Diagram execution concepts ko combine karta hai; every surface har time har layer se nahi guzarti. CLI remote spec dispatcher external HTTP backend call kar sakta hai; custom FastAPI/Flask routes bhi possible hain. Installed environment source tree se different ho sakta hai.

## 4. Repository map aur actual counts

__TOP_TABLE__

| Measurement | Meaning |
| --- | --- |
|4,143 tracked files| Git tree ka file inventory |
|2,969 `.py` paths| Includes20 cookiecutter/template Python paths |
|2,949 parsed Python files| Non-template source AST parse; no SyntaxError observed |
|38 Python package manifests| Umbrella1+core1+CLI1+cookiecutter1+extensions16+OBBject-extension1+providers17 |
|17 provider package manifests| `providers/tests` package nahi; immediate provider-directory count18 mein tests included hai |
|19 production Provider constructor sites| government_us package three provider objects contribute karta hai |
|32 raw Provider constructor sites|19production+13test fixtures; installed-provider count nahi |
|993 raw router-command decorators|985production sites+8test/example sites; runtime endpoint count nahi |
|371 standard-model class declarations|181standard-model files; multiple classes/query/data/helper roles per model possible |
|875 test_*.py files| Source file count, not executed test count |
|23,247 test_ function declarations| Static declaration count; parametrization/runtime collection ka result nahi |
|77 workflow YAML files| Configured CI/release jobs; observed passing CI runs nahi |

Raw declarations ko installed financial endpoints, unique provider names ya passed tests mein equate nahi kiya gaya. Conditional model registration aur generated runtime routes real surface ko affect karte hain. Large supplied catalogs/tests ke existence ko per-record independently audited market-data correctness nahi maana gaya.

Machine records: [original inventory](obb-evidence/inventory.json), [refined counts](obb-evidence/refined-counts.json), [complete tracked files](obb-evidence/tracked-files.json), [inventory script](obb-evidence/inventory.py).

## 5. Package construction aur complete package list

Meta-package `openbb` ka wheel ordinary all-source monolith nahi: main manifest dependencies select karta hai, hatchling build use karta hai aur wheel selection bypass/sdist README+manifest specify karta hai. Core wheel `openbb_core` aur `openbb` modules package karta hai. Individual extensions/providers ke apne versions/dependencies/entry points hain. Domain routers umbrella ke optional `routers` extra mein listed hain. Source mein folder present hona editable/distribution installed hone ka evidence nahi.

Core dependencies mein FastAPI/Uvicorn/WebSockets, Pydantic2, Requests/Aiohttp, importlib metadata, dotenv, JWT helpers aur Ruff declared hain. Pandas/Flask optional extras hain. Charting, MCP aur desktop ki apni dependency stacks hain. Main manifest mein minimum constraints hain; repo ka uv.lock alag resolved dependency record hai. This review ne packages install/update nahi kiye.

__PACKAGES_TABLE__

Table manifest-declared distribution version hai; PyPI par latest published version ka lookup claim nahi. Desktop alag JS/Rust manifests use karta hai: package.json2.0.0, tauri.conf2.0.0, Cargo1.0.2; versions homogenize nahi kiye gaye.

Sources: [[openbb_platform/pyproject.toml:1-65]], [[openbb_platform/core/pyproject.toml:1-61]], [complete manifests/dependencies/entry-points](obb-evidence/packages.json).

### Console entry points

__ENTRYPOINT_TABLE__

Console scripts ko arbitrary scripts se alag rakha gaya hai. `openbb` console command CLI hai; `from openbb import obb` Python namespace hai. Installed environment ke bina every script ka full --help/runtime import yahan execute nahi hua.

## 6. Core request execution, SDK generation aur settings

__CORE_NOTES__

### Local paths aur user-state defaults

Core constants home-directory `.openbb_platform/user_settings.json` aur `system_settings.json` define karte hain. Preferences default `~/OpenBBUserData` data directory, uske `cache`, `exports`, `styles/user` subpaths rakhti hain. Default output_type OBBject, metadata true, request_timeout60seconds, show_warnings false, dark chart/table style hain. These are source defaults, machine par real user files read hone ka report nahi. Runtime config/preferences values defaults override kar sakte hain.

Source: [[openbb_platform/core/openbb_core/app/constants.py:1-8]], [[openbb_platform/core/openbb_core/app/model/preferences.py:9-34]].

## 7. Providers, standardization aur analytics

__DATA_NOTES__

### Production provider registrations: all19 source sites

__PROVIDERS_TABLE__

Table credential requirements code declarations dikhati hai; kisi API ka free/unlimited/auth-optional hona har endpoint/request ke liye assume nahi hua. Local constructor map count aur package entrypoint name same string hona required nahi, e.g. EIA entrypoint/key differs from displayed provider names. Complete fetcher_dict expressions and source locations: [provider catalog](obb-evidence/provider-catalog.json). Catalog includes13fixtures too; table explicitly production sites select karti hai.

### Domain/utility extensions ka source map

__DOMAIN_TABLE__

### Complete production command-name index

Neeche functions ke declared names category-wise listed hain. Function name alone full public dotted command/URL nahi hai: parent-router prefixes, generated names, supported models aur installed packages route determine karte hain. Repeated names different files mein ho sakte hain; full source file, line and decorator [complete command catalog](obb-evidence/command-catalog.json) mein retained hain. Names inference se endpoints invent nahi karte.

__COMMAND_INDEX__

Standard class index: [complete model-class catalog](obb-evidence/standard-model-catalog.json). It contains file, line, class and bases. Runtime JSON schema installed provider/interface generation se derive hota hai; source list ko fully generated schema output nahi bataya gaya.

## 8. REST, MCP, CLI, desktop aur developer tooling

__SURFACE_NOTES__

## 9. Install/build/deploy ka repository-defined path

Repository docs Python-package installation `pip install openbb` aur terminal-interface installation `pip install openbb-cli` show karti hain. Pinned manifest mein optional financial router packages `openbb[routers]` extra ke through specified hain. Source developer script `python openbb_platform/dev_install.py --routers` tracked local packages editable install karke generated SDK build step run karta hai. Without --routers optional routers skip ho sakte hain. Script uv pip resolution use karta hai; source import/build code create generated files kar sakta hai, so import ko guaranteed read-only static inspection nahi maana gaya.

Docker instructions repository root build context specify karti hain: `docker build -f openbb_platform/Dockerfile -t openbb-platform .`. Image builder dependencies/install step aur non-root finalstage ka source described hai; actual image yahan build nahi hui. Desktop developer/build commands package.json scripts and CI workflows se aate hain; cross-platform Tauri output/signing yahan run nahi hua.

Sources: [[README.md:122-136]], [[openbb_platform/dev_install.py:214-290]], [[openbb_platform/Dockerfile:1-41]], [[desktop/package.json:7-17]]. Commands yahan documentation hain; koi installation/deployment execute nahi hua.

### Lockfiles, examples aur maintenance files

Python uv.lock dependency resolution preserve karta hai; desktop package-lock/Cargo.lock package-specific dependencies preserve karte hain. Template tests/devtool generators packages extend karne ke inputs hain. Examples directory mein historical-price, financial-statements, portfolio/risk, sector-rotation, Colab, LLM-tool, Streamlit aur Beam examples hain. Example presence current-provider compatibility ya benchmark correctness certify nahi karti; notebooks ko execute nahi kiya gaya.

Root pytest.ini markers, ruff.toml, ty.toml, pre-commit config, Code of Conduct aur security-reporting policy maintenance conventions define karte hain. Pre-commit generated SDK files commit hone se rokne wali check, lint/format/type checks, secret detection aur notebook-output stripping declare karta hai. Security policy advisory/email reporting route describe karti hai; third-party service security attest nahi karti.

Sources: [[.pre-commit-config.yaml:1-77]], [[pytest.ini:1-10]], [[SECURITY.md:1-12]], [tracked file index](obb-evidence/tracked-files.json).

## 10. Verification actually performed

| Check | Observed result and scope |
| --- | --- |
|Pinned source identity| HEAD matches e43353a82815ff9ba56ad1b7ad47c32729dcf314 |
|Source mutation| Tracked source diff empty at final verification |
|Archive hash and payloads| REA hash+paths+all4,143 file contents match Git objects, text EOL normalization explicit |
|Python syntax inventory|2,949 non-template files AST-parsed, zero syntax failures; not runtime imports/tests |
|Manifest inventory|38 non-template Python package manifests parsed; JS/Rust desktop manifests read separately |
|Initial wider offline test attempt| Collection stopped with ModuleNotFoundError:aiohttp; exit2; not reported as successful suite |
|Supported isolated offline subset|22tests passed in0.44seconds across optional-dependency helpers, singleton behavior, warning models |
|Full suite/provider integration/Desktop/API/MCP runtime|Not run; no complete dependency environment or live API/service credentials installed/configured |
|Source citations/local evidence/coverage|Final validator results retained below; all claims source-pinned, tested scope explicit |

22tests use unmodified copies of3 upstream test files in `obb-evidence/offline-tests/`, importing actual checkout core source via PYTHONPATH. The repository's broader conftest and plugin auto-discovery were bypassed because they pull unavailable full-install dependencies. No fake aiohttp implementation or mocked core package substituted. This limited subset is not a standard full-package CI run. Source copy hashes and command/environment scope are recorded in [test manifest](obb-evidence/offline-test-manifest.json).

The initial collection failure is an environment/dependency limitation, not proof of an upstream logic regression. See [first attempt](obb-evidence/first-attempt-offline-tests.txt), [passed subset](obb-evidence/offline-tests.txt), [runner](obb-evidence/run-offline-tests.py). This document does not claim23,247 tests passed.

### Completeness checklist

__COVERAGE_TABLE__

Covered means subsystem role and important execution path/configuration described and linked; every line of4,143 files manually audited hona imply nahi karta. Broad catalogs give file/package/model/command coverage; deep manual traces concentrate core request path, representative adapters, all main runtime surfaces, settings/security and developer pipeline. Agent notes were independently source-reference checked before integration.

## 11. Known limits and explicit unknowns

- Public snapshot vs installed environment: distribution entrypoints, extras and user configuration determine actual runtime routes/providers. Examples mentioning absent fmp/yfinance packages do not establish their presence here.
- Remote finance data quality, market delays, provider credentials, licenses, rate limits and payload changes remain provider-specific. Local schema normalization cannot guarantee correct original vendor data.
- Python query defaults/provider priority do not imply automatic failover after a vendor request fails. Core controls, adapter-specific caching and endpoint-specific retry rules are separate.
- Secret masking is not encrypted persistence; source JSON serializers can persist credential plaintext. Desktop command validation is heuristic, not a demonstrated execution sandbox. REST auth/CORS and MCP client/server auth have different scopes.
- REA static archive inventory, AST parsing,22 offline tests and source-reading do not prove cross-platform builds, production deployment safety or released artifact authenticity.
- Full historical development chronology, private hosted Workspace internals, production account/entitlement behavior, latency benchmarks, live provider responses and trading profitability were not established.

These are evidence boundaries, not pending source-code changes. No new implementation or remediation was requested, and none was added. This completed documentation task has no undisclosed install, server launch, credential read or brokerage action.

## 12. Retained evidence and how to navigate it

__EVIDENCE_TABLE__

Source citations point to the exact inspected commit. Local links resolve relative to this document. Generated catalogs and analysis utilities are review artifacts under `obb-evidence/`, not original OpenBB capabilities. The old quota checkpoint is historical; the task resumed after live300-minute quota reset and this report supersedes that partial draft.
