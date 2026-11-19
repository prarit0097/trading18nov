# Report + frontend evidence notes (Hinglish)

Scope: checkout HEAD `7657031ac01184afe2cb220f5ee3545573b5e843` verified. Read-only analysis; repo edits/provider calls/simulation runs nahin kiye. References repo-relative hain. Tests inventory hai, pass-result claim nahin.

## Actual mental model and prediction boundary

Browser Vue3 SPA hai: seed docs+requirement -> ontology/graph -> simulated personas/environment -> Twitter/Reddit-style simulation -> graph-evidence-based LLM report -> report chat/agent interview. Frontend Flask `/api` clients call karta hai; report author graph_id,simulation_id,requirement ke saath LLMClient+ZepToolsService use karta hai (`frontend/src/api/simulation.js:7`, `backend/app/services/report_agent.py:890`).

Prompts simulation ko “future rehearsal” aur agent speech ko future human behavior ki prediction bolte hain (`backend/app/services/report_agent.py:552`, `backend/app/services/report_agent.py:615`). Yeh prompt framing hai, empirical predictive accuracy ka proof nahin. Report execution outline -> retrieval loops -> generated prose -> formatting -> complete hai; independent actual-future outcome test, calibration, confidence interval ya backtest is path mein nahin (`backend/app/services/report_agent.py:1642`, `backend/app/services/report_agent.py:1699`, `backend/app/services/report_agent.py:1741`). Agent quotations synthetic simulated utterances hain, real respondents ke verified statements nahin.

## Frontend shell, routing and state

`frontend/src/main.js:1` creates app, installs router/i18n; `frontend/src/App.vue:1` router-view renders. Six routes (`frontend/src/router/index.js:1`): `/` Home; `/process/:projectId` MainView; `/simulation/:simulationId` Step2; `/simulation/:simulationId/start` Step3; `/report/:reportId` Step4; `/interaction/:reportId` Step5. Uses HTML5 createWebHistory (`:47`), so deployed host ko deep-link SPA fallback chahiye (inference).

Important: router's `Process` import is **MainView.vue**, not old `views/Process.vue` (`frontend/src/router/index.js:3`). Old Process has its own graph D3 implementation (`frontend/src/views/Process.vue:415`, `:873`) but is not current route. MainView state has step1..5, phases upload=-1/ontology0/build1/complete2, split/graph/workbench layout (`frontend/src/views/MainView.vue:94`). Routed views reuse GraphPanel + step component. Report/interaction defaults workbench (`frontend/src/views/ReportView.vue:87`, `frontend/src/views/InteractionView.vue:87`), simulation split (`frontend/src/views/SimulationView.vue:88`). Domain state lives local refs and API loads. Only shared store pendingUpload is reactive memory singleton, not persistent storage (`frontend/src/store/pendingUpload.js:6`). URL IDs recover server artifacts; chats/layout/selections mostly memory-only.

### Home and Step1

Home filters extensions pdf/md/txt, silently omits invalid files, no size/content validation in this function (`frontend/src/views/Home.vue:276`). Start stores File objects+requirement, routes Process/new (`:298`). pendingUpload clear explicit; reload/new tab loses files, and MainView shows “No pending files found” (`frontend/src/store/pendingUpload.js:13`, `frontend/src/views/MainView.vue:194`). MainView sends repeated files+simulation_requirement FormData, clears store only success, replaces URL project_id, auto-builds graph (`frontend/src/views/MainView.vue:202`). Graph clients: multipart POST `/api/graph/ontology/generate`, POST build, GET task/data/project (`frontend/src/api/graph.js:8`, `:24`, `:37`, `:49`, `:61`).

Existing project recovery: ontology_generated/no graph auto-build, graph_building/task_id resumes task poll, graph_completed loads graph (`frontend/src/views/MainView.vue:234`). Build recognizes reused response; otherwise polls task every2sec (`:275`, `:330`). Completed stops timers, refreshes project/full graph; failed stops task poll and sets error; network errors console-only (`:335`). A10sec graph polling helper at `:306` has no invocation found in active MainView: don't claim realtime initial-build graph updates are wired. Manual/final graph loads wired (`:383`); unmount timers clear (`:415`). Step1 shows ontology/stats/logs and creates simulation with both enable_twitter:true and enable_reddit:true, then routes env (`frontend/src/components/Step1GraphBuild.vue:214`).

### Step2 prepare and recovery

Auto-prepare mount (`frontend/src/components/Step2EnvSetup.vue:1089`); payload use_llm_for_profiles:true, parallel_profile_count:5 (`:780`). already_prepared loads saved artifacts; otherwise task_id/count and polls. Prepare2sec, profiles3sec, config2sec (`:835`, `:843`, `:961`). Profiles show types/count/latest; config shows agents/posts/topics/time/narrative (`:917`, `:973`). Ready/completed/already_prepared loads artifacts; failed stops all three pollers+emits error (`:743`, `:902`). Realtime and restored config paths check persisted failure before ready (`:982`, `:1048`). Network catches mostly warn and continue next interval, no backoff (`:912`, `:1029`); unmount clears all (`:1097`).

Auto rounds floor(hours*60/minutes_per_round), UI clamps max to at least40 (`:694`). custom toggle false, recommended value40 (`:675`); default does not send max_rounds; custom emitted and routed as query maxRounds (`:752`, `frontend/src/views/SimulationView.vue:153`). Estimated duration rounds*0.6 minutes is UI heuristic (`frontend/src/components/Step2EnvSetup.vue:460`). Entering env view checks live environment, attempts close(timeout10), fallback stop (`frontend/src/views/SimulationView.vue:184`); back from run similarly closes/stops then navigates even after logged errors (`frontend/src/views/SimulationRunView.vue:152`). Navigation can therefore mutate running sim state.

### Step3 run

Mount auto-starts (`frontend/src/components/Step3Simulation.vue:691`), resets local actions/status/timers; POST start hardcodes platform:'parallel', force:true, enable_graph_memory_update:true, optional max_rounds (`:383`). Revisiting run route may force rerun, not merely attach to current run. Status poll2sec/detail3sec (`:465`). Detail repeatedly fetches all_actions, appends deduped action.id or timestamp-platform-agent-action key, no pruning (`:561`). Timeline supports post/repost/like/comment/follow/search/quote/up/downvote/idle badges (`:595`).

Terminal completed/stopped uses authoritative runner_status after backend ingestion barrier, failed emits error, both stop polling (`:514`). A checkPlatformsCompleted helper exists but not authoritative branch. Stop API success immediately marks phase2/completed locally (`:441`), but report server still checks barrier. Run view refreshes graph30sec while processing/final at stop (`frontend/src/views/SimulationRunView.vue:277`, `:294`). Generate report button local double-click guard, **force_regenerate:true**, navigates by returned report_id; task_id not stored in route (`frontend/src/components/Step3Simulation.vue:645`).

## Report API lifecycle

POST `/api/report/generate` accepts simulation_id, force_regenerate defaultfalse actual JSON boolean only (`backend/app/api/report.py:32`). Missing sim400/nonexistent404; requires no live updater, no active starting/running/paused/stopping runner, and terminal completed/stopped (`:84`). Requires project exists/GRAPH_COMPLETED/graph_id/nonempty requirement and matching state.graph_id when present (`:119`). Barrier failures409, missing fields400.

Under graph_lifecycle_lock re-reads graph/sim/run/updater to prevent race; optionally reuse existing completed report if not force, else task+UUID and register graph reader lease (`:163`, `:214`, `:233`). Worker captures locale, updates TaskManager, creates ReportAgent; finally unregisters reader; thread-start failure also unregisters (`:242`, `:245`, `:291`). Plain daemon thread, not durable job queue (`:294`). Response immediate report_id/task_id/generating/already_generated:false (`:301`).

Other routes (prefix `/api/report`):

| Route | Source/contract |
|---|---|
| POST /generate/status | task_id or simulation_id completed shortcut; **no report_id accepted**, missing task400/missing task object404 (`backend/app/api/report.py:322`). |
| GET /<report_id> | serialized report or404 (`:396`). |
| GET /by-simulation/<simulation_id> | manager sim lookup (`:438`). |
| GET /list | optional simulation_id, limit default50 (`:477`). |
| GET /<report_id>/download | Markdown attachment, fallback NamedTemporaryFile delete=False (`:517`). |
| DELETE /<report_id> | whole folder/legacy files (`:563`). |
| POST /chat | simulation_id,message,chat_history; no report_id binding (`:591`). |
| GET /<report_id>/progress | progress.json or404 (`:688`). |
| GET /<report_id>/sections | saved sections, generated count, is_complete (`:729`). |
| GET /<report_id>/section/<int:index> | section_NN.md or404, actual generation starts1 (`:780`). |
| GET /check/<simulation_id> | has_report/status/id/interview_unlocked only completed (`:826`); reporting lock flag, not chat enforcement. |
| GET /<report_id>/agent-log and /console-log | incremental from_line (`:877`, `:972`). |
| GET .../agent-log/stream and .../console-log/stream | full JSON once, **not SSE/token streaming** (`:936`, `:1018`). |
| POST /tools/search and /tools/statistics | debug Zep search graph+query limit10/statistics graph required (`:1054`, `:1102`). |

Many error handlers return raw str(e)+traceback JSON (`backend/app/api/report.py:313`, `:677`, `:866`).

## ReportAgent planning, tools, exact ReAct loop

Dataclasses ReportSection(title/content), ReportOutline(title/summary/sections), Report(meta/status/markdown/error) serialize dict/markdown (`backend/app/services/report_agent.py:389`). Agent graph/sim/requirement+optional injected LLM/tools (`:890`). Planning first calls get_simulation_context **outside try** (`:1196`), passes counts/types/entities + first10 related facts; chat_json temp0.3 (`:1205`, `:1215`). Parses section titles (ignores description), title/summary; prompt says2..5 sections but parser no count/nonempty/type validation (`:571`, `:1227`). Exception inside LLM/parse try gives fixed Chinese fallback three-section “future prediction” outline; initial context failure escapes instead (`:1247`).

Tools exposed in descriptions (`:925`): insight_forge(query,optional report_context) calls graph+requirement+section context (`:977`); panorama_search(query,include_expired=True), boolean-like strings true/1/yes accepted (`:988`); quick_search(query,limit10), numeric string converted no clamp here (`:1001`); interview_agents(interview_topic or query,max_agents5 upper-clamped10, no lower clamp) calls simulation interview service (`:1014`). Old search_graph/get_simulation_context redirects plus statistics/entity summary/by-type retained in executor, not advertised (`:1029`). Errors become Chinese failure-text return values; loop counts these attempts as tool calls (`:1066`, `:1489`). This is not successful-evidence verification.

Tool calling is **prompt/text protocol**, not native provider function calling: XML `<tool_call>{name,parameters}</tool_call>` parser, fallback bare whole/trailing JSON; fallback recognizes name/tool and parameters/params and four-tool allow-list (`:1073`, `:1120`). XML path json.loads directly appends without same allow-list/key normalization (`:1083`), so malformed/wrong-shaped JSON can later fail; invalid JSON ignored. No full argument schema validation here.

Section prompt supplies report/section/requirement/tools, previous sections each truncated4000chars (`:1294`, `:1303`). It demands retrieval-only facts, original simulated-agent quotations translated into report language, no invented names/stats/tool results, no inner headings, one tool or final at a time (`:644`, `:737`). Instructions are not an independent fact checker.

Actual per-section loop: **5 iterations**, min3 desired attempted tools, MAX_TOOL_CALLS_PER_SECTION5; each LLM call temp0.5/max_tokens4096 (`:1324`, `:1343`). Executes only first tool call per iteration, appends sanitized assistant response and real observation as user message, tracks used tools/nudges unused but no strict diversity (`:1460`, `:1498`). Normal Final Answer rejected while calls<3, then suffix accepted; sufficiently searched free text without prefix also finalizes (`:1414`, `:1532`).

Tool+Final Answer conflict: first2 rejected/re-prompted (consume iterations), third truncates first closing XML tool tag and executes (`:1368`). None responses retry; after5 iterations **extra forced-final LLM call** (`:1350`, `:1546`). Thus min3 is not a hard final guarantee: fallback can return fewer/no successful calls. Force-final None returns localized placeholder and report can continue completed (`:1556`). Forced-final text doesn't pass `_strip_fake_tool_results` before return (`:1560`). Max normal section LLM calls6, excluding internal tool LLM calls. `MAX_REFLECTION_ROUNDS=3` exists (`:884`) but generate_report proceeds sections->assembly directly (`:1741`), no separate reflection/fact-check stage despite docstring.

Sanitizer removes nested/case-insensitive/attributed tool_result blocks, unmatched opening and malformed tail, preserves outside text; used normal section histories/finals and chat (`:1144`). This only strips a specific fabricated-result syntax, not all hallucinations/injections.

## Persistence, logging, partial recovery and UI reporting

Folder Config.UPLOAD_FOLDER/reports/report_id: meta.json, outline.json, progress.json, section_01.md..., full_report.md, agent_log.jsonl, console_log.txt (`backend/app/services/report_agent.py:1931`). Path helper simply joins report_id, no explicit normalized-child validation (`:1958`). Saves direct JSON/markdown writes, no atomic temp rename/manager save lock (`:2247`, `:2474`).

generate_report saves pending meta/progress, planning outline, sections as completed, final markdown/meta/progress100; exception saves failed meta/progress-1 + completed sections and returns failed object (`:1621`, `:1716`, `:1765`, `:1784`). No chapter resume entrypoint shown: new ID starts whole generation. Task progress, progress.json and meta status are separate channels; meta not updated every iteration. Percentages are orchestration progress, not forecast confidence.

save_section cleans repeated first5-line heading, demotes all remaining headings to bold, trims leading rules (`:2142`, `:2179`). assemble concatenates filename-sorted section files with report title/summary; postprocess dedup headings in5-line window, preserves recognized main/section titles, demotes others, caps blank lines (`:2287`, `:2318`, `:2348`).

Structured logs append complete details with timestamp/elapsed/report/action/stage/section; tool calls/results, LLM response, section_content and section_complete separate (`:36`, `:237`). section_complete raw full string is built after save_section but from uncleaned section_content, so UI can differ from cleaned download formatting (`:1717`, `:1721`). Console handlers attach shared report_agent/zep_tools loggers with no per-thread/report filter, so concurrent report console output can cross-contaminate (inference, `:335`). Handlers close success/failure (`:366`).

Agent log reader scans entire file, returns from_line+total_lines+has_more:false, skips malformed JSON lines (`:2066`). UI advances from_line+returned logs.length, not total_lines; skipped bad lines can create cursor lag/replayed records (inference, `frontend/src/components/Step4Report.vue:2068`). This is incremental payload, not offset-seek file reading.

Step4 polls agent log2sec/console1.5sec, initially immediate fetch and replay from0, new reportId resets refs, unmount stops timers (`frontend/src/components/Step4Report.vue:2024`, `:2157`, `:2190`). planning_complete sets outline; section_start sets active; section_complete installs full content; report_complete marks done/stops polling/unlocks Interaction (`:2037`, `:2055`, `:131`). Primary content comes logs, not backend sections/progress endpoints or GET markdown. Failed `error` action lacks terminal branch in fetchAgentLog: page can remain processing/poll forever; fetch errors warn only (`:2024`). Missing/legacy log files can leave empty UI even if report metadata is completed. Report-complete event is logged **before** final save/meta/progress; short UI/API timing disagreement or later save failure possible (inference from `backend/app/services/report_agent.py:1758`, `:1765`).

Tool cards use custom free-text parsers for insight/panorama/interview/quick search and raw-result fallback/toggle (`frontend/src/components/Step4Report.vue:498`, `:544`, `:627`, `:689`, `:904`). These aren't stable structured schema renderers; tool text language/format drift can degrade card extraction.

## Chat and interaction

POST report/chat validates sim+message, loads sim/project; graph=state.graph_id or project.graph_id, creates new ReportAgent each request (`backend/app/api/report.py:619`). No terminal-ingestion/read-lease barrier or completed-report requirement unlike generate; route ignores selected screen report_id because none sent (`:637`).

chat injects first15000chars of get_report_by_simulation markdown, last10 supplied histories, requirement/tools (`backend/app/services/report_agent.py:1833`). Two loop iterations/max1 tool each/max2 total, temp0.5; observations clipped1500chars; third final LLM call if necessary, no explicit chat max_tokens (`:1867`, `:1913`). Returns response/tool_calls/sources; sources are **query strings**, not validated citations (`:1886`, `:1924`). interview_topic tool calls may give empty source query. Histories forwarded unchanged except last10 slice; no role/content schema validation here (`:1857`).

Step5 uses local per-target chat histories (`frontend/src/components/Step5Interaction.vue:429`, `:491`); report chat sends last10 prior role/content, stores only answer/response+timestamp, ignores returned sources/tool_calls in send handler (`:682`). Direct agent chat POSTs batch interview using profile **array index as agent_id** and last6 history entries embedded in Chinese prompt (`:712`). Result preference reddit then twitter then first result; only one platform answer shown (`:744`). Survey sends selected index/question batch, chooses reddit/twitter per respondent (`:805`). This is synthetic-agent survey, not real public sample.

Step5 loads report then full logs0 once to restore outline/sections (section_index<100); no ongoing poll (`:875`, `:892`). Profiles realtime GET without platform means backend-selected platform; UI assumes profile index identity (`:917`). Mount and immediate watchers both call loads; changing reportId watcher does not itself clear chat caches/sections (`:940`). Chat cache not persisted to storage/server. ReportView/InteractionView load report->sim->project->**current project.graph_id**, not report.graph_id: old report can display rebuilt graph (inference from `frontend/src/views/ReportView.vue:145`, `frontend/src/views/InteractionView.vue:146`).

## Graph and locale

GraphPanel D3/SVG maps first non-Entity label to type, encounter-order ten-color palette, filters edges missing either endpoint (`frontend/src/components/GraphPanel.vue:284`, `:328`, `:369`). Self relations collapse one loop/node retaining details; parallel edges spread curvature (`:395`). Force link/manybody-400/center, zoom0.1..4, node drag threshold3px, selection highlights incident edges and detail raw data (`:472`, `:492`, `:650`). Deep graph watch rebuilds layout, previous sim stopped, resize listener; unmount stops sim/removes listener (`:333`, `:786`, `:804`). Display positions not calibrated causal/probability embeddings.

i18n eagerly loads root locale JSON via glob filtered languages manifest; localStorage locale or zh, fallback zh (`frontend/src/i18n/index.js:1`). Manifest zh/en/es/fr/pt/ru/de with llmInstruction, no Hindi (`locales/languages.json:1`). Switcher sets locale/localStorage (`frontend/src/components/LanguageSwitcher.vue:37`); Axios sends Accept-Language (`frontend/src/api/index.js:14`); worker captures locale. Hardcoded English/Chinese statuses, times and agent-history prompts remain (`frontend/src/views/MainView.vue:137`, `frontend/src/components/GraphPanel.vue:306`, `frontend/src/components/Step5Interaction.vue:725`).

## Client surface, mismatch and limitations

Graph client methods listed above; simulation client exports create/prepare/prepare-status, get/list simulation, profiles/realtime, config/realtime, start/stop, run-status/detail, posts(offset/limit), timeline(round bounds), agent-stats, filtered actions, close-env/env-status, batch interview, history limit20 (`frontend/src/api/simulation.js:7`, `:15`, `:23`, `:31`, `:40`, `:50`, `:59`, `:68`, `:76`, `:85`, `:93`, `:101`, `:109`, `:120`, `:132`, `:144`, `:153`, `:161`, `:169`, `:177`, `:186`). Omitted platform intentionally omitted from params for profiles/posts so backend selects. HistoryDatabase loads20 history records and offers modal navigation project/simulation/report (`frontend/src/components/HistoryDatabase.vue:403`, `:413`, `:424`, `:435`, `:446`); route changes/home reactivation reload history and observer controls stacked-card expansion (`:462`, `:543`, `:549`). It is an API-backed history viewer, not a database engine.

- Axios baseURL VITE_API_BASE_URL or absolute localhost5001, timeout300000ms/default JSON (`frontend/src/api/index.js:5`). Vite dev port3000/proxy/api->5001 (`frontend/vite.config.js:14`), but default absolute URL bypasses relative proxy; remote deployment without env tries user's localhost (inference).
- Response unwraps response.data; rejects success:false; non2xx backend error/message replaces error.message. Despite “retry mechanism” comment, no retry implementation (`frontend/src/api/index.js:26`). Polling repeatedly requests independently.
- Exported getReportStatus issues GET `/api/report/generate/status?report_id=...`, backend only POST JSON task_id/simulation_id (`frontend/src/api/report.js:15`, `backend/app/api/report.py:322`). rg finds only export, no callers; active Step4 log polling avoids broken wrapper. Don't overstate as current main-flow failure.
- get_report_by_simulation returns **first os.listdir match**, not newest/completed (`backend/app/services/report_agent.py:2547`). list_reports separately sorts newest (`:2568`). Regenerated reports accumulate, so chat/check/cache/by-simulation can pick an older or failed first match; screen report isn't bound to report-chat request.
- force flag only affects completed-cache reuse; no active same-simulation report dedupe visible, independent requests can create separate reader leases/workers (`backend/app/api/report.py:214`). Local double-click guard covers only one component (`frontend/src/components/Step3Simulation.vue:651`).
- Daemon workers/direct files: abrupt server exit may leave partial pending/planning/generating files; no restart/resume shown (`backend/app/api/report.py:294`, `backend/app/services/report_agent.py:1621`). Concurrent JSON read/direct write may throw; manager doesn't use atomic rename in cited saves.
- Report/chat/survey custom regex Markdown feeds v-html with **no escaping or HTML sanitizer** in functions (`frontend/src/components/Step4Report.vue:51`, `:1874`, `frontend/src/components/Step5Interaction.vue:273`, `:557`). User chat itself also renders this way. HTML injection/XSS surface is code-based inference, no exploit executed.
- setInterval async pollers have no in-flight guard/cancellation; slow requests can overlap/out-of-order; logs/actions grow unbounded in shown handlers (`frontend/src/components/Step4Report.vue:2157`, `frontend/src/components/Step3Simulation.vue:465`). Agent-log endpoint rescans full file; full details/results retained (`backend/app/services/report_agent.py:2095`, `frontend/src/components/Step4Report.vue:2035`).
- Download temp fallback delete=False has no cleanup shown, and omits explicit UTF-8 unlike normal saves (`backend/app/api/report.py:538`).
- Frontend package scripts only dev/build/preview, no test runner/script; Vue3.5/router4.6/i18n11.3/D3 7.9/Axios1.18/Vite7.3 (`frontend/package.json:6`). Parent independently verified Node prerequisite discrepancy and build; use parent's verification logs for actual runtime results.

## Test evidence inventory

`backend/tests/test_report_tool_result_sanitizer.py:6` parametrizes fake tool-result stripping including malformed/nested variants; `:25` preserves legitimate text. These establish fixture-level syntax sanitization, not hallucination absence or forecast accuracy.

`backend/tests/test_zep_report_barrier.py:26` ingestion wait; `:67` active rerun not returning stale completed report; `:113` failed ingestion after restart cannot report; `:149` graph reader lease blocks graph start/delete. Monkeypatched route/lifecycle contracts, not provider end-to-end behavior or prediction validation. This agent did not execute tests; parent has separate validation output.
