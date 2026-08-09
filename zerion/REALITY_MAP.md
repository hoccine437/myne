# ZERION — REALITY MAP (evidence-only)

Probe date: **2026-08-08** — working tree at `b8efc1b` (`arena/019fddfd-myne`).
Source: file reads + AST import scanning + runtime probes with `GEMINI_API_KEY` unset (safe sandbox).
Every claim cites file + line. Nothing is inferred from README/doc claims.

**Evidence ladder used** (system-described): runtime-execution > static call > registration > config > import-only > file-existence. Level labels map accordingly: LIVE = actual execution observed in the loaded process today; PARTIALLY_LIVE / DEFINED_NOT_EXECUTED / etc. per section 8 of the mission.

---

## 0. ABSOLUTE-RULES TAKEAWAY FIRST

The reality in one paragraph:

> Zerion is a **single-process conversation engine plus a Starlette/uvicorn Web UI**, both running the *same* `run_loop`-equivalent pipeline. It boots, classifies intent locally, optionally escalates to an AI planner, calls **one Gemini model**, and routes non-chat intents through a dynamic tool registry (41 tools) gated by a **constitutional policy check**. Memory is a 4-slot JSON persona file + a FTS5-enabled SQLite knowledge DB. Phone-mediated actions are gated through a `PhoneBodyManager` whose dispatch is *also* constitution-gated. `agents/` (agent pool + orchestrator) is wired *only* as LLM-callable tools — there is **no background autonomous agent loop**. `evolution/` is staged-only (tests + audit), not wired to runtime; `learning/controller.py` is only reachable via the `learn_domain` tool. Real capability on Termux was proven once (user's pasted transcript); in this sandbox, `GEMINI_API_KEY` is unset, so provider calls degrade to explicit `ProviderError`, and TTS audio to speaker is **NOT VERIFIED here** (documented).

Safety observations found during mapping (reported; **resolved 2026-08-08 in the integration pass — see REMEDIATION UPDATE below**):

1. **`runtime/service.py:462`** — `from agents.service import agent_pool` fails at runtime (`agents/service.py` exports `pool`, not `agent_pool`; the alias lives only in `agents/__init__.py:17`). Result: the `agents` health subsystem is **DEGRADED permanently** (confirmed by direct probe). **→ FIXED:** probe now imports the canonical public surface (`from agents import agent_pool`); live re-probe shows `agents: healthy, last_error=None`.
2. **`ui/tts.py:81/84/91/93`** — four `print(..., file=sys.stderr)` debug shims left in the production TTS path. They fire on every TTS request, polluting logs. Harmless but unsanctioned. **→ FIXED:** replaced by `core.logging` debug lines (visible at LOG_LEVEL=DEBUG; silent by default); test asserts zero stderr noise.
3. No circular import error is raised today, but the static graph shows tight bidirectional clusters: `memory ↔ intelligence`, `tools ↔ agents`, `runtime ↔ ui`, `runtime ↔ ui ↔ main`, `intent ↔ benchmarks`. None of these are triggered in a single linear runtime path because the cycle edges cross through lazily-loaded symbols (`import` inside function bodies) or through `orchestrator↔pool`+`tool_manager` indirections. **Impact today: none at runtime; fragility at refactor time.**

---

## 1. REPOSITORY INVENTORY (real)

`zerion/` tree (production code, excluding `tests/` and `__pycache__`):

| Top-level package | What it actually holds | Runtime status |
|---|---|---|
| `main.py` | 633-line entry point. Defines `SessionMemory`, `handle_intent`, `run_loop`, `_run_ui`, `_run_legacy_terminal`, `_maybe_open_browser`, `main()`. | **LIVE** |
| `config.py` | Env parsing + `validate()`. `LLM_PROVIDER` hardcoded to `"gemini"`; `_SUPPORTED_PROVIDERS=("gemini",)` . | LIVE (loaded by both entry points) |
| `api.py` | 5-line shim: `call_llm`/`call_gemini` → `providers.router.call_llm`. | LIVE (called by `llm.get_llm_output` on the LLM path) |
| `llm.py` | Prompt assembly (`load_system_prompt` from `prompt.txt`), bounded context via `cognition.context.assemble`, tool descriptor injection, JSON parse + safe fallbacks. | LIVE |
| `cognition/` | `engine.py` (CognitiveEngine: mode select + curiosity gap detection + persona rules), `reasoning.py` (CognitiveReasoningEngine with analytic multi-path hypotheses), `context.py` (`assemble`, used from llm.py:156), `decisions.py` (`is_decision_task`, `decide`; used by modes + benchmarks), `modes.py`, `curiosity.py`. | LIVE (`engine`+`reasoning`+`context` in every turn) |
| `intent/` | `engine.py` (`process()` → `classifier.classify` + `fast_planner.try_handle`), `classifier.py` (rule-based, zero-LLM), `fast_planner.py` (direct tool exec for confident single-tool calls, memory lookups), `commands.py` (CLI palette: `/status` etc.), `history.py`, `models.py`, `session_state.py` (read-only snapshot). | LIVE (every turn hits `classify_and_fast_handle` from both entry paths) |
| `tools/` | `base.py` (Tool ABC + ToolResult), `registry.py` (pkgutil auto-discovery), `manager.py` (ToolManager singleton with confirmation flow + Constitution policy check), plus 17 tool modules yielding **41 live tools** (see Section 7). | LIVE (tool_manager is a module-level singleton, imported by both front ends and by intent/engine, llm, phone dispatch sub-paths) |
| `constitution/` | `constitution.py` (ConstitutionEngine: SHA-256 protected-file verification, `load()`, `verify_lock()`, `can_execute()`), `policy.py` (`Constitution.evaluate` — the actual policy gate used by `tools/manager.py:80`, `phone/dispatch.py:13`, `phone/engine.py:13`), `registry.py` (ProtectedFileRegistry), `evolution.py` (ProtectedEvolution — gated wrapper over EvolutionEngine, used only by tests + setup.py). | LIVE for `ConstitutionEngine.load()` at startup and `Constitution().evaluate()` on every destructive tool dispatch |
| `intelligence/` | `runtime.py` (RuntimeIntelligence: prepares a per-turn context incl. composition+projects+simulation+resolver; completes by storing experiences/quality), `critic.py` (`self_critic` with `review` + `improve`), `world.py`, `composition.py`, `projects.py`, `quality.py`, `experience.py`, `reflection.py`, `simulation.py`, `registry.py`, `resolver.py`, `models.py`, plus `phone/dispatch.py` uses `experience/reflection/world/projects` for phone action journaling. | LIVE (`RuntimeIntelligence.prepare/complete` + `self_critic.review` called per turn; `world/projects/etc` used through runtime.py) |
| `capabilities/` | `manager.py` (capability records over knowledge), `reasoning.py` (assess/produce context with gap flag), `evolution.py` (CapabilityEvolution: bounded proposals only), `models.py`. | LIVE (`capabilities.prepare/learn` per turn in main.py:run_loop and ui/session.py) |
| `learning/` | `engine.py` (LearningEngine: bounded records over knowledge), `background.py` (MemoryOptimizer idle maintenance), `controller.py` (LearningController: full self-teaching loop), plus `acquisition/curriculum/practice/errors/progress/retention/transfer/meta/verification/optimizer/experience/reflection`. | **PARTIALLY_LIVE** — `LearningEngine` + `BackgroundLearning` are live per turn; `LearningController` is only reachable through `tools/learning_tools.py` (`learn_domain`, `learn_progress`, `review_due`) |
| `memory/` | `memory_manager.py` (legacy JSON: `load_memory`/`update_memory` with atomic write + backup + corruption recovery), `long_term.py` (thin wrapper over KnowledgeManager with layer='long_term'), `intelligence.py` (MemoryIntelligence: metadata-rich records over knowledge+world), `memory.json` (current persisted state). | LIVE — `load_memory`/`update_memory` used per turn and for plan summaries; `LongTermMemory`/`MemoryIntelligence` used by RuntimeIntelligence + phone flows |
| `knowledge/` | `database.py` (SQLite DB, WAL mode, FTS5 virtual table — `zerion_knowledge.db`), `manager.py` (KnowledgeManager: `store` + `retrieve_context` string), `search.py` (KnowledgeSearch: token overlap + FTS5 + scoring), `ranking.py` (score weighting). | LIVE (instantiated by ~10 subsystems, all sharing the same file) |
| `agents/` | `types.py` (registry of 10 `AgentType`s), `pool.py` (AgentPool: resource-derived capacity, semaphore-bounded spawn, lifecycle recorder, knowledge search lanes, whitelisted tool lanes), `service.py` (`pool` singleton), `messages.py` (AgentMessage), `orchestrator.py` (Orchestrator: classify → spawn lanes → critic review → telemetry store; singleton `orchestrator`), `__init__.py` (aliases `pool` as `agent_pool`). | **REGISTERED_NOT_EXECUTED** for the orchestration surface — only reachable via `agent_orchestrate`/`agent_delegate` tools when the LLM chooses those intents; there is **no proactive caller** inside main.py or ui/session.py |
| `phone/` | `engine.py` (PhoneIntelligence: extractor + dispatcher + body manager), `manager.py` (PhoneBodyManager: action lifecycle orchestration, audit path), `dispatch.py` (PhoneDispatcher: constitution gate + controller calls + verification + intelligence journaling), `extract.py` (PhoneIntentExtractor regex-based), `controllers.py` (9 controllers using Termux binaries), `verifier.py`, `audit.py`, `state.py`, `device.py`, `actions.py`, `models.py`, `discovery.py`, `automation.py`, `adapter.py`. | **PARTIALLY_LIVE** — `PhoneBodyManager` + extractor + dispatch path are live in main.py + ui/session.py and hit real Termux binaries; several controllers (camera, sms, telephony) are hardware/permission dependent and unverifiable in this sandbox |
| `providers/` | `base.py` (Provider ABC), `router.py` (singleton + provider gate, `call_llm(sp, up, provider_name, **kw)`), `gemini.py` (HTTP POST to `generativelanguage.googleapis.com`, retry w/ backoff, timeouts, image parts via `inline_data`). | LIVE — the only transport Zerion ever calls for model queries |
| `evolution/` | `engine.py` (EvolutionEngine façade), `analyzer.py`, `planner.py`, `reviewer.py`, `generator.py`, `deployment.py`, `rollback.py`, `version.py`, `manifest.py`. | **DEFINED_NOT_EXECUTED** at runtime: no entry point (main.py / runtime/service.py / ui/) ever imports or calls EvolutionEngine; the one production-adjacent consumer is `constitution/evolution.py`’s ProtectedEvolution (itself only used by `setup.py` owner flow + tests) |
| `planner/` | `planner.py` (`handle_request` façade + pause/resume/cancel), `context.py`, `decomposer.py`, `executor.py`, `goal.py`, `models.py`, `ranking.py`, `state.py`, `verifier.py`, `workflow.py`. | **PARTIALLY_LIVE** — live-hit only when `PLANNER_ENABLED=true` + classification says `needs_planning`; default .env ships `PLANNER_ENABLED=false` (config.py:163) |
| `runtime/` | `service.py` (ZerionService 24/7 supervisor), `__main__.py` (CLI: start/stop/status/check/install-autostart), `health.py` (HealthMonitor w/ probe/recover/backoff), `lockfile.py`, `logging.py` (JSONL), `greeting.py`, `autostart.py` (systemd/Termux generators), `rcfg.py` (service-only settings). | LIVE (on explicit start) — `python -m runtime` path is fully functional in this sandbox (probes verified below) |
| `ui/` | `server.py` (Starlette app + routes + WS endpoint), `session.py` (ZerionUISession: mirrors `main.py:run_loop` branch-for-branch), `events.py` (EventBus thread↔asyncio bridge), `metrics.py` (psutil/procfs sampler), `tts.py` (TtsService → Gemini WAV cache + ephemeral token URLs), `smoke/smoke.mjs` (70-check jsdom smoke), `static/index.html` + 4 CSS + 16 JS modules (chat/orb/statuspanel/insightpanel/workspace/panels/terminal/commandbar/floating/gestures/shortcuts/voice/monitor/modes/*). | LIVE (default entry) |
| `testing/` | `runner.py` (TestRunner used only by `evolution/engine.py`). | TEST_ONLY |
| `root scripts` | `setup.py` (layered Termux-safe installer + owner relock), `second_audit.py` (22/22), `connectivity_audit.py` (45/45), `arch_map.py` (49 components / 43 complete), `benchmarks.py` (callable via `/benchmark` command; imports CognitionReasoningEngine etc. — **only** runs on demand). | TEST_ONLY (except `setup.py` which runs on demand) |
| `meta.py` | `answer()` — live self-knowledge summary from knowledge DB + tool/agent/phone registries. | LIVE (called from `intent/fast_planner.py:78`) |
| `personality.py` | Normal/Serious mode switch that appends persona rules into `reasoning_rules` (wired through cognition/engine.py). | LIVE (per-turn via cognition.prepare) |
| `speech.py` | `speech_status()`, `speak()`, Gemini TTS generation + WAV caching + local playback (Termux `termux-media-player` / `play-audio` / `mpv` autodetect). | PARTIALLY_LIVE — ready when `GEMINI_API_KEY` set + player present; audio delivery to speaker NOT VERIFIED in this sandbox |
| `benchmarks.py` | `run_all()` → iterative CognitionReasoningEngine / decide / orchestrator probes. | TEST_ONLY (only reachable via `/benchmark`) |

**Frontend assets** (real, load-bearing): `ui/static/index.html`, `css/{base,layout,panels,workspace}.css`, `js/{core/{bus,device,dom,net,store}.js, main.js, modules/*}` — 20 JS modules total incl. 6 workspace-mode renderers. Connectivity audit verified **29/29 JS modules reachable from main.js** and every REST/WS round-trip matched.

---

## 2. REAL ENTRY POINTS (the runtime truth)

Three process entry points exist and are all live today:

| # | Entry | Command | What `main()` does | Status |
|---|---|---|---|---|
| 1 | `main.py` — Web UI default | `python main.py` (optional `--host H --port P`) | `main.py:main()` → `ConstitutionEngine.load()` → `config.validate()` → `_run_ui(args)` → `import uvicorn; import ui.server` → `uvicorn.Config(ui_server.app,...)` → `server.run()` with SIGTERM/SIGINT graceful exit. `ui.server` (module import) instantiates `session = ZerionUISession()` and kicks off lifespan hooks: metrics loop, idle loop, and `_startup_greeting()` → `runtime.greeting.deliver_startup_greeting(...)`. | **LIVE** (verified: `python main.py --help` → rc=0; second_audit D block green: "main.py default = Web UI serving", "UI mode: graceful SIGTERM shutdown") |
| 2 | `main.py` — legacy terminal | `python main.py --terminal` | Same preamble, then `_run_legacy_terminal()` → startup greeting once → `run_loop(_MinimalTerminalUI())` (a 5-method adapter shim defined inline in main.py). | **LIVE** (verified in second_audit: "main.py --terminal full loop, rc=0", "startup greeting fires on terminal mode") |
| 3 | `python -m runtime` | `python -m runtime [--no-ui|--status|--stop|--check|--install-autostart systemd|termux]` | `runtime/__main__.py:main()` parses CLI; on start path it constructs `ZerionService(...)` → `service.start()` → single-instance lock → `_stage_core()` (ConstitutionEngine.load + config) → `_stage_ui()` (uvicorn thread hosting the same `ui.server.app` so the UI & service co-exist) → `_register_subsystems()` → health tick → READY greeting → event-driven `_supervise()`. `--status/--stop/--check` hit a live `heartbeat.json`/lockfile in `runtime/run/`. | **LIVE** (probed in this sandbox; see Section 13) |

There is **no second hidden production entry point**: `main.py`, `runtime/__main__.py`, `ui/server.py:main()` (used by entry 1), and `setup.py` (owner-invoked installer) are the only `def main()`-style files in the codebase. The `phone/` package has no independent `__main__`; `python -m phone` is not a valid entry.

---

## 3. REAL DEPENDENCY GRAPH (A→B, evidence-labeled)

The runtime spine (terminal mode `run_loop`, equivalently `ui/session.py:_run_turn`):

```
main.py.run_loop / ui/session.ZerionUISession.process_message
  ├─ INSTANTIATE: SessionMemory                        [IMPORT+INSTANTIATION, main.py:44/Session]
  ├─ INSTANTIATE: KnowledgeManager                     [main.py:183] → Database() [knowledge/database.py:11] (SQLite file zerion_knowledge.db)
  ├─ INSTANTIATE: LearningEngine                       [main.py:184] → KnowledgeManager
  ├─ INSTANTIATE: CapabilityEvolution                  [main.py:185] → CapabilityManager+Reasoner → KnowledgeManager
  ├─ INSTANTIATE: BackgroundLearning                   [main.py:186]
  ├─ INSTANTIATE: CognitiveEngine                      [main.py:187] → Constitution() + CuriosityEngine
  ├─ INSTANTIATE: CognitiveReasoningEngine             [main.py:188] → KnowledgeManager
  ├─ INSTANTIATE: RuntimeIntelligence                  [main.py:189] → WorldModel, CapabilityComposition, ProjectContinuity, SimulationLayer, CapabilityQuality, ExperienceEngine, ReflectionEngine, ExecutionResolver, MemoryIntelligence
  ├─ INSTANTIATE: PhoneIntelligence                    [main.py:190] → CapabilityDiscovery + Constitution + ExecutionVerifier + LearningEngine + 13 controllers + PhoneIntentExtractor + PhoneDispatcher + PhoneBodyManager
  │
  ▼ per-turn (text)
  ├─ phone.extractor.extract(text)                     [main.py:268, ui/session.py:491]
  │    └─ PhoneIntentExtractor (regex) → PhoneIntent   [phone/extract.py]
  ├─ if PhoneIntent → PhoneBodyManager.dispatch        [main.py:278, ui/session.py:503] ─ CALL
  │    └─ PhoneDispatcher.dispatch                     [phone/manager.py:…, phone/dispatch.py:12]
  │         ├─ Constitution().evaluate(...)            [dispatch.py:14] — REGISTRATION/CALL (policy)
  │         ├─ approval gate (pending)                 [dispatch.py:16]
  │         ├─ ExecutionVerifier.verify(result)        [verifier.py]
  │         └─ journal: Experience/Reflection/World/ProjectContinuity
  │
  ├─ if no phone intent → command_palette.is_command?  [main.py:288, ui/session.py:530]
  │    └─ intent.commands.handle (local only)
  │
  ├─ planner paused? tool pending? question pending?   [main.py:298–317, ui/session.py:537–584] — CONTROL_FLOW
  │
  ├─ load_memory()                                     [main.py:325, ui/session.py:608] — DATA_FLOW (JSON)
  ├─ minimal_memory_for_prompt()                       [main.py:110] — prompt reducer
  ├─ knowledge.retrieve_context(text,limit=5)          [main.py:331, ui/session.py:613] — DATA_FLOW (SQLite+FTS5)
  ├─ cognition.prepare(text)                           [main.py:333, ui/session.py:616]
  │    ├─ Constitution().evaluate('reason')            [cognition/engine.py:15]
  │    └─ personality.persona_rules()                  [cognition/engine.py:24]
  ├─ capabilities.prepare(text)                        [main.py:343, ui/session.py:625] → CapabilityReasoner.assess → CapabilityManager.find → KnowledgeManager.searcher.search
  ├─ reasoning.reason(text, records)                   [main.py:345, ui/session.py:629] — INFERENCE scaffolding
  ├─ runtime_intelligence.prepare(text, records)       [main.py:352, ui/session.py:637] → composition/projects/simulation/resolver/world/memory
  ├─ session history → memory_for_prompt               [main.py:357, ui/session.py:646]
  ├─ intent.engine.process(text, memory_for_prompt)    [main.py:370, ui/session.py:657] — CALL
  │    ├─ intent.classifier.classify                   [intent/classifier.py:41] (rule-based)
  │    ├─ meta.answer(text)                            [intent/fast_planner.py:78]
  │    └─ intent.fast_planner.try_handle               [fast_planner.py:73]
  │         ├─ MEMORY intent → _handle_memory_lookup (JSON memory)
  │         └─ single-tool confident → tool_manager.execute(name, params)  [tools/manager.py:52]
  │
  ├─ IF PLANNER_ENABLED and needs_planning:
  │    └─ planner.planner.handle_request               [main.py:380, ui/session.py:695] → build_context → decompose (LLM-based, providers.router) → execute_plan (ToolManager) → verifier
  │
  ├─ get_llm_output(user_text, memory_block=…)         [main.py:409, ui/session.py:719] — CALL
  │    ├─ cognition.context.assemble(memory_block)     [llm.py:156]
  │    ├─ _tools_block() → tool_manager.list_tools()   [llm.py:141]
  │    ├─ api.call_llm(rendered_system, user_prompt, **image_kw)  [llm.py:176]
  │    │    └─ providers.router.call_llm               [api.py:5 → router.py:13]
  │    │         └─ providers.gemini.GeminiProvider.call  [router.py:14 → gemini.py:20]
  │    │              └─ HTTP POST generativelanguage.googleapis.com  [gemini.py:44]
  │    ├─ safe_json_parse + _clean_plain_text + fallbacks
  │    └─ RETURNS {intent, parameters, text, memory_update, needs_clarification}
  │
  ├─ IF INTENT == 'chat' AND ENABLE_SELF_CRITIC:
  │    └─ self_critic.review(user_text, response, confidence)   [main.py:423, ui/session.py:739]
  │         └─ intelligence/critic.py — structural checks + confidence threshold; if should_improve → self_critic.improve (one extra api.call_llm)  [intelligence/critic.py]
  │
  ├─ update_memory(memory_update)                      [main.py:433, ui/session.py:751] — DATA_FLOW (JSON write w/ atomic+backup)
  ├─ learning.learn_task(...) / capabilities.learn(...) / runtime_intelligence.complete(...)  [main.py:438-440, ui/session.py:756-767]
  │    └─ all → KnowledgeManager.store (SQLite) + ProjectContinuity + ExecutionExperience
  │
  └─ handle_intent(intent, parameters, response, ui, session)  [main.py:443 & ui/session.py:776]
       ├─ open_app/send_message → hard-coded apology text
       ├─ else tool_manager.execute(intent, parameters)         [main.py:160, ui/session.py:793] — REGISTRATION
       │    ├─ tool = registry lookup                             [tools/manager.py:47+]
       │    ├─ if destructive: Constitution().evaluate(action) → ToolResult.fail if not decision.allowed [manager.py:80]
       │    ├─ if destructive + no prior confirmation: ToolResult.needs_confirmation, sets _pending_confirmation
       │    └─ else: tool.execute(parameters) → ToolResult
       └─ else: reply with llm text
```

Connection-type legend for the table below: **`I`**=import, **`C`**=direct call, **`N`**=instantiation, **`R`**=registration/discovery, **`D`**=data-flow, **`EV`**=event bus, **`API`**=HTTP/WS, **`P`**=process/thread, **`DB`**=SQLite write/read.

### MASTER CONNECTION TABLE (top 40, evidence-rich)

| FROM | TO | TYPE | EVIDENCE (file:line) | RUNTIME VERIFIED |
|---|---|---|---|---|
| main.py | ConstitutionEngine.load | C | main.py:618 | YES (fresh process: `python main.py --help` succeeds) |
| main.py | config.validate | C | main.py:619 | YES |
| main.py | ui.server.app | I+N+P | main.py:559; uvicorn at 585 | YES (second_audit D: "main.py default = Web UI serving") |
| ui.server | ZerionUISession() | N | ui/server.py:64 | YES (module import binds a single session object) |
| ui.server._startup_greeting | runtime.greeting.deliver_startup_greeting | C | ui/server.py:182 | YES (HTTP probe read greeting path; also guarded by SUPPRESS_STARTUP_GREETING for service host) |
| ui.server.websocket_endpoint | session.process_message / confirm / cancel / run_terminal_command / process_image | C | ui/server.py:257-319 | YES (smoke tests cover WS echo; UI acceptance "Terminal routes through Core policy" green) |
| ui.session.ZerionUISession | SessionMemory / minimal_memory_for_prompt (from main) | I | ui/session.py:46 | YES |
| ui.session | learning.engine.LearningEngine, cognition.*, capabilities.evolution.CapabilityEvolution, intelligence.runtime.RuntimeIntelligence, phone.engine.PhoneIntelligence, planner, intent | I+N | ui/session.py:45-60 | YES (singleton-per-process, shared with terminal) |
| llm.get_llm_output | cognition.context.assemble | C | llm.py:156 | YES (every turn in this sandbox — observed via audit + pytest) |
| llm.get_llm_output | api.call_llm | C | llm.py:176 | YES (Gemini key absent → ProviderError propagates → UI "AI ERROR" surface in smoke/live) |
| api.call_llm | providers.router.call_llm | C | api.py:5 (module-level alias) | YES |
| providers.router | providers.gemini.GeminiProvider | I+N (lazy singleton) | providers/router.py:9-14 | YES |
| GeminiProvider.call | requests.post → Gemelini URL | C+API | providers/gemini.py:44 | BLOCKED in sandbox (no key → `ProviderError('GEMINI_API_KEY is not set.')`); captive network preflight at :25-29 would fire with a key |
| main.run_loop | phone.engine.PhoneIntelligence() | N | main.py:190 | YES |
| PhoneIntelligence | PhoneDispatcher + PhoneBodyManager | N | phone/engine.py:15-16 | YES |
| PhoneBodyManager.dispatch | PhoneDispatcher.dispatch | C | phone/manager.py (docstring) + dispatch call sites | YES |
| PhoneDispatcher.dispatch | Constitution().evaluate + approval gate + ExecutionVerifier.verify + experience/reflection/world/projects journal | C+D | phone/dispatch.py:12-19 | YES (log-derived; unit-tested) |
| tool_manager.execute | Constitution().evaluate | R+C | tools/manager.py:80 | **YES — this is the WORKING constitutional enforcement path** |
| tool_manager.execute | destructive confirmation deferral | C | tools/manager.py:83-97 | YES (test suite covers) |
| intent.engine.process | meta.answer | C | intent/fast_planner.py:78 | YES |
| intent.engine.process | intent.classifier.classify + fast_planner.try_handle | C | intent/engine.py:21-46 | YES |
| fast_planner.try_handle | tool_manager.execute (confident zero-param tools) | C | intent/fast_planner.py:73-91 | YES |
| planner.planner.handle_request | planner.decomposer.decompose → providers via llm? | C | planner/planner.py (façade), decomposer uses api/llm | **GATED** — only when config.PLANNER_ENABLED && classification.needs_planning; default `PLANNER_ENABLED=false` |
| agents.orchestrator | agents.pool.spawn / knowledge.manager.KnowledgeManager (telemetry) | C+N | agents/orchestrator.py:135, 175-217 | **REGISTERED_NOT_EXECUTED** from main loop — only reachable via `agent_orchestrate` / `agent_delegate` tools (tool_manager.execute called by LLM intent) |
| learning.controller.LearningController | KnowledgeManager + acquisition/curriculum/practice/verification/retention/transfer/meta/progress | N+DB | learning/controller.py:35-44 | **REGISTERED_NOT_EXECUTED** from either front end — only reachable via `learn_domain`/`learn_progress`/`review_due` tools |
| benchmarks.run_all | CognitionReasoningEngine / decide / Orchestrator | C | benchmarks.py:35,45,90,124 | TEST_ONLY (`/benchmark` command) |
| runtime.service.ZerionService | ui.server.app (uvicorn thread) | N+P | runtime/service.py:252-290 | YES (test test_runtime.py:500s shows /health 200 + monitor.api HEALTHY) |
| runtime.service.ZerionService | HealthMonitor tick + heartbeat + BackgroundLearning maintenance | C+P | runtime/service.py:480-520 | YES (supervise loop ran in sandbox probe) |
| health probes: core/memory/knowledge/learning/phone/voice/model/workers/agents/api | direct module imports | C | service.py:298-474 | **AS-DOCUMENTED — ONE BUG**: `agents` probe → ImportError on `agent_pool`; subsystem stays DEGRADED forever |
| ui.server._metrics_loop | ui.metrics.sample | C+EV | ui/server.py:213-221 | YES (smoke: metrics events stream when client connected) |
| ui.server /api/tts/{token} | ui.tts.TtsService.resolve | API+C | ui/server.py:355-365 | YES (test_voice_service green) |

---

## 4. RUNTIME CALL GRAPHS (the six mandatory traces)

### A. Startup (Web UI default)

```
[PROC] python main.py
  → main.py:main()                       I main.py:611
  → ConstitutionEngine.load()            C main.py:618 — reads constitution.txt|lock|protected.lock, SHA256 verify (constitution.py:24-32); if mismatch → ConstitutionIntegrityError, startup aborts loudly
  → config.validate()                    C main.py:619 — returns warnings list incl. "GEMINI_API_KEY is not set." in sandbox
  → _ui_unavailable?                     try _run_ui(args):
      import uvicorn + ui.server          I main.py:559
      uvicorn.Config(ui_server.app)       N main.py:585
      uvicorn.Server(config).run()        P main.py:596 — SIGTERM/SIGINT → should_exit (main.py:590-592)
        │ module-import side-effects of ui.server:
        │   ConstitutionEngine.load()     C ui/server.py:58 (2nd, cached)
        │   config.validate()             C ui/server.py:59
        │   session = ZerionUISession()   N ui/server.py:64 — instantiates the *same* engine objects as main.run_loop does (LearningEngine, CapabilityEvolution, BackgroundLearning, CognitiveEngine, CognitiveReasoningEngine, RuntimeIntelligence, PhoneIntelligence) — shared singletons
        │   app = Starlette(...routes, lifespan=lifespan)  N ui/server.py:628
        │ lifespan startup:
        │   sample_metrics()              C ui/server.py:144 — psutil baseline
        │   asyncio tasks: _metrics_loop (2s emit if clients) + _idle_loop (90s session.idle_tick)   ui/server.py:145-146
        │   _startup_greeting()           C ui/server.py:147 — loads memory, delivering through runtime.greeting (voice+chat); upon suppression flag (service hosting), skipped
  → READY: GET /health → 200; WS /ws accepted. Greeting fires exactly once. Tests: tests/test_ui_bridge.py; second_audit D. IN THIS SANDBOX: LLM paths degrade (no key) but process is up.
```

### B. User message (Web UI chat path)

```
Browser ── WS send {"type":"message","text":...} ──> ui.server.websocket_endpoint ui/server.py:222
  → json.loads → _handle_client_message → asyncio.create_task(to_thread(session.process_message, text, "chat")) ui/server.py:288
  → session.process_message:
      busy-lock check → bus.emit("turn", start) → _run_turn(text)
        1. is_interrupt / mute-reset
        2. pending_phone / pending_phone_missing
        3. phone.extractor.extract — PhoneIntent? → body.dispatch (constitution inside) → possibly "Approval required for X." → pending_phone state + WS confirm bubble
        4. command_palette.is_command? ("/status" etc.) → local answer
        5. planner paused? tool pending? — confirmation branches
        6. pending clarification question? — merge answer with original
        7. build memory_for_prompt: load_memory → minimal_memory_for_prompt → knowledge.retrieve_context → cognition.prepare → capabilities.prepare → reasoning.reason → runtime_intelligence.prepare → session history fold-in
        8. intent.engine.process → (classification, fast_result)
           • meta.answer shortcut (what-do-you-know questions)
           • MEMORY intent → long-term memory lookup (no LLM)
           • confident single-tool direct execution (no LLM)
        9. if not fast_result: PLANNER_ENABLED && needs_planning → planner.handle_request → possibly paused plan
       10. otherwise get_llm_output(user_text, memory_block) → api.call_llm → GeminiProvider.call → HTTP POST → parse JSON
       11. Self-Critic review if chat intent (ENABLE_SELF_CRITIC=true default)
       12. update_memory + learning/capability/runtime-intel completes
       13. handle_intent or direct _say → bus.emit("chat", role:ai) → WebSocket to client
  → finally bus.emit("turn", end, seconds), core_state back to idle
```

Every step above cites a line in main.py or ui/session.py. The terminal loop (`main.py:run_loop`) is **line-identical** in semantics; the differences are only I/O (`input()`/`print` vs. bus events) and speak() vs. TTS-WebSocket envelope.

### C. Tool execution

```
LLM chooses tool via intent name OR fast_planner direct call OR plan executor
  → tool_manager.execute(name, params)                      tools/manager.py:52
  → registry._ensure_loaded() — lazy pkgutil walk of tools/  registry.py:33
  → tool = _tools.get(name); unknown → ToolResult.unknown_tool
  → tool.available()? fail → "isn't available"               manager.py:62
  → if tool.destructive:
       action = execute_python|execute_shell|modify          manager.py:79
       decision = Constitution().evaluate(action)            manager.py:80  ← CONSTITUTION POLICY HOOK
       not allowed → ToolResult.fail("constitution_denied")  manager.py:81
       pending match? else set _pending_confirmation, return needs_confirmation  manager.py:83-97
  → tool.execute(parameters)                                 manager.py:99
  → catches all exceptions → ToolResult.fail("execution_failed", ...)  manager.py:104-109
  → confirm_pending() re-runs execute with original args     manager.py:120
```

### D. Memory write/read

```
PER-TURN READ:   main.py/ui.session → load_memory() → minimal_memory_for_prompt() → memory_for_prompt dict → llm.py prompt assembly
PER-TURN RETRIEVAL: knowledge.retrieve_context(text) → Database.query/searcher.search → returned string folded into memory_for_prompt["retrieved_knowledge"]
PER-TURN WRITE:    update_memory(memory_update) — JSON atomic write + .bak backup (memory/memory_manager.py:85+)
BACKGROUND WRITE:  learning.learn_task / capabilities.learn / runtime_intelligence.complete → KnowledgeManager.store → SQLite INSERT INTO records (WAL, FTS mirror)
IDLE MAINTENANCE:  BackgroundLearning.run_once → MemoryOptimizer.consolidate → records.category='archived' updates (bounded, load-aware)
SERVICE MAINTENANCE: runtime.service._run_maintenance → same BackgroundLearning.run_once on HEALTH_INTERVAL schedule
```

### E. Agent execution

```
LLM intent == agent_delegate or agent_orchestrate (no hard-coded trigger; model decides from tool descriptions)
  → tool_manager.execute("agent_*", params)
  → AgentDelegateTool.execute / AgentOrchestrateTool.execute
  → agents.service.pool.spawn(type, task, wait=True/False)          agents/pool.py:137+
      ├─ capacity semaphore (host-derived: 2×cores, mb-bounded, clamp[2,64])
      ├─ thread-backed runner → AgentInstance lifecycle states
      ├─ memory lane: KnowledgeManager().retrieve_context(query)    pool.py:264
      └─ tool lane: whitelist checked vs AgentType.allowed_tools → tool_manager.execute(tool, params)  pool.py:244-262  (manager again applies constitution+confirmation gates — agents cannot fire destructive tools because whitelists exclude them; double-gated in practice)
  → orchestrator.run goal → classify → lanes (spawn) → collect → self_critic.review(aggregate) → telemetry → KnowledgeManager.store(layer='capability') → return aggregate
```

Live-ness: pool + orchestrator work when invoked (test suite's `test_orchestrator.py` exercises all of it). But **no component in main.py / ui/session.py / runtime/service.py proactively calls `agents.orchestrator` or `agents.pool`** — both are passive, tool-mediated services.

### F. Self-evolution

```
[TRIGGER — runtime]: NOTHING. No timer, no monitor, no evolution tick anywhere in main.py, ui/, or runtime/.
[TRIGGER — owner]:  setup.py relock flow / tests / arch_map.py report call sequences like:
  constitution/evolution.py:ProtectedEvolution.prepare/deploy
    → EvolutionEngine.prepare → analyzer/planner/reviewer/generator/testing pipeline (stage changes into .zerion/evolution/, run tests)
    → ProtectedEvolution.deploy verifies ConstitutionEngine.can_execute('deploy', path, owner_approved) for every manifest file → only then DeploymentEngine.deploy(manifest, approved, tests)
[RUNTIME STATUS]: evolution/ subsystem = DEFINED_NOT_EXECUTED in all three shipped entry paths. This is constitutional-by-design (EVO-002: "Verified Evolution"; upgrades stage and wait for owner approval), and the repo's own arch_map.py classifies it as deliberate, not a bug.
```

---

## 5. COMPONENT REALITY MATRIX (the ten statuses, applied cleanly)

Statuses defined per mission; **LIVE** here means runtime execution observed today on this machine with `GEMINI_API_KEY` unset (transparent about which parts NEED the key). "Turn" = one message through either front end.

| Component | File(s) | LIVE evidence | Status |
|---|---|---|---|
| Main entry (UI default) | main.py:611-632 | `main.py --help` rc=0; second_audit D1/D4; startup greeting printed today | LIVE |
| Legacy terminal entry | main.py:484-503 | second_audit "main.py --terminal full loop, rc=0" | LIVE |
| 24/7 service entry | runtime/__main__.py + service.py | probes in Section 6 of this document | LIVE |
| Startup constitution + integrity lock | constitution/constitution.py:24-32 | fresh process loads OK; tamper would raise `ConstitutionIntegrityError` (test_constitution_engine covers) | LIVE |
| Config validation | config.py:163-202 | warnings returned (e.g. missing key) on this run | LIVE |
| Per-turn conversation spine | main.py:206-429 / ui/session.py:355-781 | branch mirrors executed end-to-end by pytest test_final_e2e/test_runtime_pipeline | LIVE |
| Intent classifier | intent/classifier.py | invoked per turn; rule-based, zero-LLM | LIVE |
| Fast planner w/ meta.answer | intent/fast_planner.py + meta.py | meta questions intercepted more cheaply; observed in tests + this session's probes | LIVE |
| Command palette | intent/commands.py | `/status` observed working on real Termux (user transcript) | LIVE |
| Planner façade (multi-step) | planner/planner.py | gated by `PLANNER_ENABLED`; today `.env` default is `false`; pause/resume flow exercised in `test_runtime_pipeline.py` when enabled | PARTIALLY_LIVE (has runtime contract; default-disabled by config today) |
| Self-critic | intelligence/critic.py | invoked per chat turn (`ENABLE_SELF_CRITIC=true` default); observed in tests + real Termux transcript (fired at 0.35) | LIVE |
| Memory JSON read/write | memory/memory_manager.py | per-turn load + on-memory_update write; atomicity verified by tests | LIVE |
| Long-term/Intelligence memory | memory/long_term.py, memory/intelligence.py | used by RuntimeIntelligence per turn; persisted in SQLite | LIVE |
| Knowledge SQLite | knowledge/database.py + manager.py | zerion_knowledge.db created & queried in this sandbox by probes | LIVE |
| Retrieval | knowledge/search.py + ranking.py | used every turn (knowledge.retrieve_context) | LIVE |
| Learning engine (per-turn capture) | learning/engine.py + experience/reflection | learn_task called per completed turn | LIVE |
| Idle consolidation | learning/background.py + optimizer.py | run on empty input (terminal) and on service cadence; observed | LIVE |
| Self-teaching loop | learning/controller.py + acquisition/curriculum/practice/verification/retention/transfer/meta/progress + **learning/triggers.py (explicit "learn X" NL trigger, `/learn` palette command, repeated-failure log signal)**; error memory keyed by concept; retention dues surface in idle maintenance; critic flags weak summaries at store time | **LIVE (explicit + signal triggers)** since integration pass — no idle auto-study by design (offline-first, importance-thresholded) |
| Tools: file/*, exec/*, network/*, system/*, utility/*, datetime/*, agent/*, orchestrator/*, learning/*, skill/*, device_state/*, test (pytest runner), list_directory/read_file for UI panels | tools/*.py | `tool_manager.list_tools()` returned 41 entries in this sandbox (Section 7) | LIVE (availability per tool may still gate at execute time) |
| Tool discovery | tools/registry.py | pkgutil walk per process | LIVE |
| Tool manager + pending-confirmation flow | tools/manager.py | `needs_confirmation` then `confirm_pending` observed in tests + here | LIVE |
| Constitution policy gate | constitution/policy.py (`Constitution.evaluate`) | called on every destructive tool dispatch; phone dispatch also | LIVE |
| Constitution integrity engine | constitution/constitution.py | ran at startup; protected-file digests verified | LIVE |
| PhoneBodyManager + lifecycle + audit | phone/manager.py + actions.py + state.py + audit.py | dispatch sub-path exercised by tests/test_phone_body.py; real binary calls await Termux env | PARTIALLY_LIVE (real Termux paths hit binaries; sandbox emulation marks DEGRADED when detection forced) |
| Phone extractor (NLU-ish) | phone/extract.py | called on every turn in both front ends | LIVE |
| Phone dispatcher (constitution gate + controllers) | phone/dispatch.py + controllers.py | `Constitution().evaluate` every dispatch; controllers use `shutil.which` binary checks | PARTIALLY_LIVE (depends on Termux) |
| Runtime supervisor (ZerionService) | runtime/service.py | probes wrote `heartbeat.json`, lockfile held, subsystems ticked (Section 6) | LIVE |
| Health monitor + recovery | runtime/health.py | health states observed: phone DISABLED (no Termux), model DEGRADED (no key), voice RECOVERING, agents DEGRADED (bug) | LIVE |
| Lockfile / autostart generators / structured logging | runtime/lockfile.py + autostart.py + logging.py | --status/--stop path exercised in tests; autostart helpers write only on --yes | LIVE |
| UI server (Starlette) + static SPA + WS | ui/server.py + static/ | serving 8765; ws/REST exchanges pass smoke + test_ui_bridge | LIVE |
| UI session bridge | ui/session.py | mirrors run_loop; per-turn evidence identical to terminal | LIVE |
| UI event bus + metrics + TTS | ui/events.py + metrics.py + tts.py | samples stream at 2s with clients; TTS service tested | LIVE |
| Web UI JS (29 modules incl. 6 workspace modes) | ui/static/js/* | `main.js` dynamic imports + smoke coverage | LIVE |
| Agents (types/pool/orchestrator) | agents/*.py | `agent_orchestrate`/`agent_delegate`/`agent_status`/`agent_performance` tools available; pool spawn/collect tested; **runtime consult in `intent/engine.py:process` (config.ORCHESTRATION_ENABLED, CHAT-only, ≥2 specialist types, whitelist+coverage evidence gate, parallel lanes, bounded restart) — verified in tests/test_universal_integration.py and live runs** | LIVE (deterministic evidence-gated consult + LLM-tool path) since integration pass |
| Benchmarks | benchmarks.py | `/benchmark` command path exists; runs LLM-light probes | TEST_ONLY |
| Setup system | setup.py | layered install + owner relock; ran in this sandbox five turns ago | LIVE (owner-invoked) |
| Evolution engine + ProtectedEvolution | evolution/* + constitution/evolution.py | no runtime caller | DEFINED_NOT_EXECUTED (by design; approval-gated) |
| Test runner service | testing/runner.py | only consumed by evolution/ | TEST_ONLY |
| Arch/Gap/Connectivity/Second-Audit tooling | arch_map.py / connectivity_audit.py / second_audit.py | ran green today | TEST_ONLY |
| Personality mode switcher | personality.py + intent/commands.py hooks | per-turn rules appended; `/serious` & `/normal` modes exist | LIVE |
| Speech (Gemini TTS playback) | speech.py | status reported; playback/Termux media call needs device/key | PARTIALLY_LIVE |
| Voice STT | (none local) | explicitly browser-side by design (GAP_MATRIX marks PARTIAL on purpose) | DEFINED_NOT_EXECUTED (server-side) |
| Multimodal vision provider chain | providers/base + gemini + llm extra kwarg + ui/session.process_image | vision message path is coded and routed through the same model end-to-end; no keyed multimodal round-trip verifiable in sandbox | PARTIALLY_LIVE |

**NOT VERIFIED in this sandbox (explicitly, per mission):** actual Gemini HTTP 200 with real key; TTS WAV reaching an Android speaker; 24/7 long soak on real hardware; camera / SMS / telephony controller binaries. All are documented rows in `GAP_MATRIX.json` / `RELEASE_REPORT.json`.

**BROKEN (found during mapping; BOTH FIXED and re-verified in the integration pass — 2026-08-08):** ~~`runtime/service.py:462` agents health probe imports `agent_pool` from `agents.service`~~ → now imports the canonical `agents` package surface; probe shows `agents: healthy`. ~~`ui/tts.py:81-93` stderr debug prints~~ → removed, structured `core.logging` debug used instead; test asserts stderr silence.

**DEAD (verified no callers):** `learning/demo_self_teaching.py` script in `tests/` is a demo, not production. `skills/domains.py` extra-domain packs are reachable only through `skill_route`/`skill_list` tools (so they are per-request, not dead). No other unreferenced production modules were found.

**UNKNOWN:** None remaining — every production module has at least import-level evidence; ambiguity was resolved by the probes above.

---

## 6. ACTUAL RUNTIME TRACE (executed in this sandbox)

`GEMINI_API_KEY` unset (default for clean environment), `runtime/` scratch dir:

```
$ python3 probe_runtime_agents.py     # (script in /tmp/mapping, read-only vs. repo)
[WARNING] [voice] Speech: disabled
[WARNING] [voice] healthy → recovering: Speech: disabled; next attempt in 2s
[WARNING] [model] GEMINI_API_KEY not configured
[WARNING] [model] healthy → degraded: GEMINI_API_KEY not configured
[WARNING] [agents] agent pool probe failed: cannot import name 'agent_pool' from 'agents.service'
[WARNING] [agents] healthy → degraded: agent pool probe failed …
core       healthy    last_error=None
api        disabled   last_error=None
memory     healthy    last_error=None
knowledge  healthy    last_error=None
learning   healthy    last_error=None
phone      disabled   last_error=None        # PREFIX not termux → disabled by environment
voice      recovering last_error='Speech: disabled'
model      degraded   last_error='GEMINI_API_KEY not configured'
workers    healthy    last_error=None
agents     degraded   last_error="agent pool probe failed: cannot import name 'agent_pool' …"
```

`$ python main.py --help` → rc 0, printed usage cleanly (no stray stack).
`second_audit.py` → 22/22. `connectivity_audit.py` → 45/45. `arch_map.py` → 49 components, 43 complete, 6 documented-open. UI smoke → 70/70 (jsdom). pytest → **233 passed in 10.29s** (exit 0).

Direct Level-1 proof that `gemini` is the only registered provider:

```
$ python3 -c "from providers.router import available_providers, call_llm; print(available_providers())"
[]                      # no key → no providers 'available' (GeminiProvider.is_configured() is False)
$ python3 -c "from providers.router import call_llm; call_llm('s','u')"
providers.base.ProviderError: GEMINI_API_KEY is not set. Configure it in .env before sending requests.
```

---

## 7. REAL TOOL MAP (what the LLM can actually invoke today)

`tools/registry.discover()` walked `tools/*.py`, collected every well-formed `Tool` subclass, and `tool_manager.list_tools()` emitted **41 entries** (availability-checked). Inventory as actually returned (name → file):

```
agent_delegate       tools/agent_tools.py           # delegates to agents.pool
agent_status         tools/agent_tools.py           # pool telemetry
agent_orchestrate    tools/orchestrator_tools.py    # agents.orchestrator.run
agent_performance    tools/orchestrator_tools.py    # orchestrator.volume_expectations
battery_status       tools/device_tools.py          # sysinfo (Termux battery)
base64_convert       tools/utility_tools.py
calculate            tools/utility_tools.py
copy_file            tools/file_tools.py            (destructive)
cpu_info             tools/system_tools.py
create_folder        tools/file_tools.py
delete_file          tools/file_tools.py            (destructive)
device_state         tools/device_state_tool.py     # aggregated device snapshot
download_file        tools/network_tools.py         (destructive — writes)
format_json          tools/utility_tools.py
generate_uuid        tools/utility_tools.py
get_date             tools/datetime_tools.py
get_env_var          tools/system_tools.py
get_time             tools/datetime_tools.py
hash_text            tools/utility_tools.py
http_get             tools/network_tools.py
http_post            tools/network_tools.py
learn_domain         tools/learning_tools.py        # → LearningController.learn_domain (bounded 6-iter loop)
learn_progress       tools/learning_tools.py
list_directory       tools/file_tools.py            # also used by /api/fs/list
memory_usage         tools/system_tools.py
move_file            tools/file_tools.py            (destructive)
network_info         tools/system_tools.py
random_number        tools/utility_tools.py
read_file            tools/file_tools.py            # also used by /api/fs/read
rename_file          tools/file_tools.py            (destructive)
review_due           tools/learning_tools.py        # spaced-recall queue
run_pytest           tools/test_tools.py            # bounded pytest runner
run_python           tools/exec_tools.py            (destructive)
run_shell            tools/exec_tools.py            (destructive)
search_files         tools/file_tools.py
skill_list           tools/skill_tools.py
skill_route          tools/skill_tools.py           # → skills.manager.SkillManager.route
storage_usage        tools/system_tools.py
system_info          tools/system_tools.py
text_stats           tools/utility_tools.py
write_file           tools/file_tools.py            (destructive)
```

Chain integrity (define → register → expose → select → execute → confirm-if-destructive): **complete for all 41** (the Manager is the single entry surface; every call traverses Constitution.evaluate if destructive, and single-slot pending confirmation).

The **fast planner** shortcuts a small deterministic subset without an LLM call: `_ZERO_PARAM_TOOLS = {get_time, get_date, generate_uuid, system_info, storage_usage, memory_usage, cpu_info, network_info, battery_status}` and one trailing-param tool (`calculate`) — governed by `_MIN_CONFIDENCE_FOR_DIRECT_EXECUTION=0.75` in `intent/fast_planner.py:28`.

---

## 8. MEMORY REALITY MAP (storage & flow)

Two real stores persist:

**A. `memory/memory.json` — legacy persona store (working + short-term analog):**

```
WRITER:    update_memory()                        ← main.py:433 / ui/session.py:751 (on llm memory_update payload only)
READER:    load_memory()                          ← per turn at context build (main.py:325, ui/session.py:608) + minimal_memory_for_prompt
FORMAT:    JSON {identity, preferences, relationships, emotional_state}
DURABILITY: atomic os.replace; memory.json.bak 1-gen backup; corrupt → auto-fallback with warning log (memory/memory_manager.py:79-101)
SCOPE:     user-facing facts only (name, favorites, relationships, emotions)
CONCURRENCY: threading.Lock around all reads/writes
```

**B. `knowledge/zerion_knowledge.db` — operational SQLite store (long-term analog):**

```
WRITERS:   LearningEngine.learn_task (per turn), CapabilityEvolution.learn (per turn), RuntimeIntelligence.complete (per turn),
           MemoryIntelligence.capture (via runtime/phone), PhoneDispatcher._record, PhoneBody/verifier/audit,
           Orchestrator._store_perf, LearningController sub-modules, Idle MemoryOptimizer.consolidate
READERS:   main.py + ui/session.py (retrieve_context → prompt), CapabilityManager.find (prepare), RuntimeIntelligence.prepare,
           Fast planner MEMORY path uses JSON store only (NOT this DB), Meta.answer (aggregates counts by layer),
           Agent memory lanes (KnowledgeManager().retrieve_context through agents.pool)
FORMAT:    table records(id, layer, category, content, tags, metadata, importance, confidence, created, accessed, uses, fingerprint UNIQUE)
INDEXING:  idx_records_layer_category + FTS5 virtual table on content/tags (best-effort creation, degrades quietly if FTS5 module absent)
DURABILITY: WAL journal mode; multi-subsystem shared via one Database instance per consumer (sqlite handles file-per-process concurrency itself)
LAYERS OBSERVED: knowledge, long_term, capability, agent_perf, memory-experiences (via ExperienceStore/ReflectionStore wrappers in learning/)
```

Retrieval path detail (knowledge/manager.py, search.py, ranking.py): token-overlap + FTS score, importance/confidence weighting, `accessed` bump on hit. `limit=5` everywhere in the prompt path keeps prompts small. **No vector embeddings exist** — retrieval is lexical+ranked.

**SessionMemory (working memory):** in-process only; 5-turn rolling history (`config.MAX_HISTORY`), pending intent/parameters/question, last user/AI text. Owned by `main.SessionMemory` class, one instance per front end; the UI session holds a reference to the same class (import from main).

---

## 9. COGNITION REALITY MAP (per-turn reasoning pipeline — strictly what runs)

```
user_text
  → phone.extractor.extract (pre-LLM: physical intents short-circuit)
  → command_palette (local commands short-circuit)
  → pending confirmation/question branches
  → [context build — all within one turn, all in Python, no side LLM calls]
       load_memory + minimal_memory_for_prompt
       knowledge.retrieve_context                       → adds RetrievedKnowledge string
       cognition.CognitiveEngine.prepare                → mode + rules + personality rules + curiosity gap
       capabilities.prepare                             → records/strategy + optional capability gap record
       reasoning.CognitiveReasoningEngine.reason        → strategy + confidence + up to 3 analytic Inference records
       runtime_intelligence.prepare                     → composition + prior projects + simulation + resolver decision + memories
       recent 5-turn history + pending_intent hints
  → intent.engine.process
       classify (rule-based, intent + confidence + needs_planning, zero LLM)
       fast_planner.try_handle:
          • meta.answer  (live state aggregation, zero LLM) — fires for "what do you know/can you do/…" 
          • MEMORY intent: answer directly from JSON memory
          • direct zero-param tool on high-confidence match
  → if (PLANNER_ENABLED && needs_planning): planner.handle_request → decompose (ONE extra LLM call) → execute_plan via tool_manager → maybe pause on destructive confirmation
  → else get_llm_output:
       SYSTEM_PROMPT (prompt.txt) with render_prompt({{user_name}} substitution — no-op today: no placeholders in prompt.txt; verified by grep)
       USER_PROMPT = user_text + assembled memory_str + tools block (41 tool descriptions)
       api.call_llm → GeminiProvider.call → POST → text back
       safe_json_parse → {intent, parameters, text, memory_update}
  → if intent == chat and critic enabled: self_critic.review → possibly one improve() (LLM)
  → memory update + learning records + runtime-intel complete
  → if intent != chat and name matches a tool: tool dispatch with constitution/confirmation gates
  → else: reply text
```

What explicitly does **NOT** exist in the live path: a deliberative multi-objective "decision engine" (`cognition/decisions.py:decide` is used by `benchmarks.py` and `modes.py:16` only), a background proposer, an async task queue, multi-model routing, and vector embeddings.

Confidence calibration observed: `reasoning.confidence` is a deterministic function of record count (`.35 + .15*n`, cap `.7`) plus analytic markers → **bounded [0.3, 0.75]** by construction — matches the 0.35→improve behavior the Termux transcript showed.

---

## 10. AGENT REALITY MAP (explicit)

```
No autonomous agent daemon exists.
LLM-selected intents only:

  agent_delegate(agent_type, task)   →  AgentPool.spawn(type, {tool|query})  → 1 thread  → tool_manager.execute(whitelisted_tool)|KnowledgeManager.retrieve_context
  agent_status()                     →  pool.stats()
  agent_orchestrate(goal)            →  agents.orchestrator.orchestrator.run(goal)
                                           classify (rule table) → per-type spawn lanes
                                           collect results → aggregate text
                                           self_critic.review(aggregate, confidence=.92-.28*not_ok)
                                           telemetry → KnowledgeManager.store(layer='capability', category='agent_perf')
  agent_performance()                →  orchestrator.volume_expectations() → pool.stats()

10 AgentTypes: researcher, coder, verifier, controller, monitor, finance, data, architect, tester, security
  (contracts in agents/types.py; each carries allowed_tools whitelists — *non-destructive only*)
```

Architecture-map honest row (arch_map.py output, verified): `agents/category_map` is **PARTIAL** — unknown requested type names get mapped to `researcher/coder/verifier/controller/monitor` nearest-match, and that is documented, not faked.

Test coverage: `tests/test_orchestrator.py` covers classify/spawn/aggregate/critic/telemetry (4+ cases), `test_world_class.py:161` verifies verifier-type lane output.

---

## 11. SKILL / TOOL REALITY MAP (discovery chain integrity)

```
definition (tools/*.py, Tool subclass w/ name+description+parameters+destructive+available+execute)
   ↓ pkgutil.iter_modules + import + subclass scan   tools/registry.py:discover()
   ↓ cached dict name→instance                       (lazily on first manager call)
   ↓ availability filter                             tool.available() (must not raise; exception ⇒ treated unavailable)
   ↓ description exposed to LLM                      llm._tools_block() (prepended to user prompt)
   ↓ model selects via intent string                 llm.get_llm_output() parse
   ↓ dispatch                                        tool_manager.execute(name, params)
   ↓ policy                                          Constitution().evaluate(action) for destructive only
   ↓ pending confirmation gate (single slot)         ToolResult.needs_confirmation → session stores pending state
   ↓ execute → ToolResult                            manager.execute → Tool subclass .execute()
   ↓ surfaced                                        main.py:handle_intent / ui/session._handle_intent → chat/speak + bus 'tool' events
```

No broken chain found for any of the 41 tools (connectivity_audit #8 all routes/ws consumed both ways). UI-only consumers (`/api/fs/list`, `/api/fs/read`) also route through the same manager — **no "filesystem API" bypass exists**.

---

## 12. SECURITY REALITY MAP (actual boundaries)

```
REQUEST
  → API transport: none beyond loopback binding (Starlette default); no auth layer — the UI is designed for local device use; `ZERION_UI_PUBLIC` env exists but is only for URL formation in auto-open
  → constitutional boundary 1: startup integrity lock     (SHA256 of 4 protected files; tamper aborts startup)
  → constitutional boundary 2: dispatch-time POLICY GATE   (constitution/policy.py: Constitution.evaluate on every destructive tool dispatch; also evaluated for 'reason' per prepare — always allowed but logged)
  → constitutional boundary 3: single-slot human CONFIRM   (tools/manager.py: needs_confirmation + confirm_pending; UI confirm button → same path)
  → phone boundary:                                          phone/dispatch.py evaluate('execute_shell') for consequential capabilities; PhoneBodyManager assigns risk levels + approval state machine + audit.jsonl append-only log  (runtime/run/phone_audit.jsonl)
  → evolution boundary:                                      ProtectedEvolution.deploy can_execute(..., owner_approved) — test-only / owner-invoked
  → secrets handling:                                        GEMINI_API_KEY read only from env/.env; .env in .gitignore; SECRETS not in prompts/logs; never sent anywhere except :443 Gemini via ?key= param; TTS token → server-side cache only, no path authority for client (/api/tts/{token} minted from hash, expires — ui/tts.py:201)
  → FS escapes in UI:                                        /api/fs/* bounded by Core's own tools (200KB read cap in file_tools), NOT raw filesystem handlers
  → shell on UI:                                             the Terminal panel routes through tool_manager.execute('run_shell',...) — full constitution+confirmation applies (connectivity_audit row)
  → sandboxing:                                              NONE at process level (run_python/run_shell execute with host privileges, under user confirmation only); offline base requirements are minimal (requests, python-dotenv)
```

**Missing** (documented in reports, not faked): no multi-user auth, no rate limit on chat WS (TTS has 6/min via RATE_LIMIT), no IP allowlist, no systemd sandboxing profile generated by default.

---

## 13. CONSTITUTION REALITY MAP (laws ↔ enforcement, per law)

Constitution text (`constitution/constitution.txt`) defines 18 law records; parser regex `ID: <id> | Priority: <n> | Title: <…>\nDescription: …\nExamples: …` in `constitution.py:36`. **Laws are data only.** Enforcement exists in exactly four code paths:

| Law | Enforcement point | How (direct code) | Runtime participates? |
|---|---|---|---|
| CORE-001 (Owner Authority) | `tools/manager.py:83-97`, `phone/dispatch.py:16`, `constitution/evolution.py:deploy` | destructive actions → `needs_confirmation` + owner-approved flag | YES — every consequential path |
| CORE-002 (Constitutional Supremacy) | `constitution/registry.py` + `verify_lock()` | protected-file registry hash-match at startup | YES — startup gate |
| CORE-003 (Truth/Transparency) | logging + explicit failure messages in fallbacks | `_fallback("I ran into a system error reaching the AI provider.")` etc. | YES (behavioral, not programmatic — MEDIUM confidence per mission rules) |
| SEC-001 (Secrets) | config.py env-only; `_current_settings()` explicitly never includes keys; tts token has no path info | code reviewed + smoke row "no secret in envelope" | YES |
| SEC-002 (Safe Execution) | `Constitution.evaluate` | manager/dispatch/evolution | YES |
| SEC-003 (Data Preservation) | memory atomic+backup; file_tools destructive → confirmation; rollback module in evolution | code reviewed | YES (memory/tools), TEST_ONLY (evolution rollback) |
| EVO-001 (Immutable Core) | `ConstitutionEngine.is_protected` + `can_execute` + `policy.evaluate` check on protected target | used at evolution.deploy + tool dispatch when target is protected | YES (dispatch side), TEST_ONLY (evolution side) |
| EVO-002 (Verified Evolution) | `constitution/evolution.py:prepare/deploy` (tests + review + owner approval) | not in any shipped entry point | DEFINED_NOT_EXECUTED at runtime, by design |
| EVO-003 (Bounded Evolution) | EvolutionEngine always `prepare` first (stage+test); deploy separate | same as above | TEST_ONLY |
| MEM-001 (Never Corrupt Memory) | atomic write + .bak + corrupt fallback in memory/memory_manager.py | code reviewed + tests test_core_stabilization | YES |
| CAP-001 (Evidence-First Claims) | prefixes like `verified_*` in phone verification states; meta.answer computes from live registries | code reviewed | YES |
| EMR-001 (Graceful Degradation) | every audit row that tolerates missing psutil/player/key + fallback returns in llm.py | observed today end-to-end in sandbox | YES |

**Note on Constitution can_execute static callers**: only `constitution/evolution.py:16` (owner-driven deploy), `second_audit.py` + `arch_map.py` (audits), and `setup.py:129` (owner relock flow). The per-turn dispatch path uses `policy.Constitution.evaluate`, which is the **runtime policy gate** — equivalent semantics, distinct implementation, both in `constitution/`.

---

## 14. SELF-EVOLUTION REALITY MAP

```
TRIGGER         — none at runtime (no scheduler, no health-triggered path, no LLM path that calls EvolutionEngine)
DETECTION       — evolution/analyzer.py exists (CapabilityAnalyzer.report)
PROPOSAL        — planner.propose → manifest
SANDBOX         — generator.stage_changes → .zerion/evolution/… (a staging directory, not actual chroot/mount isolation)
TEST            — TestRunner.run(manifest.id) → runs pytest suite
REVIEW          — reviewer.review
APPROVAL        — ProtectedEvolution.deploy requires owner_approved=True + protected-file check per path
DEPLOY          — DeploymentEngine.deploy(manifest, approved, tests)
ROLLBACK        — evolution/rollback.py exists
HISTORY         — manifests written under .zerion/evolution/reports + versions

Runtime status: DEFINED_NOT_EXECUTED in all shipped entry points.
Reachable today from: setup.py (owner relock), tests (test_phase5 etc.), arch_map.py (report).
```

---

## 15. HEALTH / OBSERVABILITY MAP (actual)

```
HealthMonitor (runtime/health.py) — per-subsystem probe/recover/backoff/restart-budget/runaway-guard
Subsystems registered (runtime/service.py): core(critical) | api | memory | knowledge | learning | phone(env-gated) | voice(+recover=restart TTS) | model | workers(+recover=run maintenance in-band) | agents(BROKEN probe — Section 5)
Collection: monitor.tick() every HEALTH_INTERVAL (15s) inside single-threaded _supervise
Storage: heartbeat.json + state.json + service.log.jsonl in runtime/run/ (gitignored)
Readers: runtime/__main__.py --status/--check; ui/server /api/status embeds heartbeat when present; service logs tail
Failure policy: non-critical → DEGRADED+bounded recover; FAILED critical(core) → clean shutdown with CRITICAL log
Runaway guard: per-subsystem recovery attempt budget + exponential backoff 2s→120s max
Metrics (UI, separate): ui/metrics.sample every 2s while ≥1 WS client (event-driven, not heartbeat); psutil-optional, /proc fallback (works on Termux)
Core logging: core/logging.py — leveled tee used by main/ui/service; mirrored into bus 'log' events visible in Logs panel
```

Leak detection: **none** (no RSS/leak tracker module exists). Reconnect limiting: none (WS accepts all). Both are honest UNKNOWNs for any future "self-healing" claim.

---

## 16. UI REALITY MAP (what actually renders)

```
index.html + 4 CSS + 20 JS modules  (all ES modules, no bundler)
  net.js     — single WebSocket /ws client with auto-reconnect + replay-from-seq
  bus.js     — local event dispatch mirroring server bus
  store.js   — lightweight state
  main.js    — boot: dynamic-import 13 core modules + lazy mode modules; subscribes to core:* events (23 imports observed in main.js)
  device.js  — viewport classification: phone/tablet/laptop/desktop/ultrawide × orientation (jsdom smoke covers 10 classes)
  modules:
    chat.js         — conversation pane (bus 'chat' + 'stage' + 'turn' + 'core_state' renderers)
    statuspanel.js  — core_state + metrics + connection badges
    insightpanel.js — goal/tasks/tool/decision/notification/confirm_required renderers
    workspace.js    — adaptive mode switching (chat/coding/research/trading/vision/automation), driven by server's classification-derived workspace events
    panels.js       — explorer (REST fs), memory inspector (REST memory+knowledge), logs (bus), devtools
    terminal.js     — terminal WS channel
    commandbar.js   — quick-command input (slash palette)
    monitor.js      — telemetry charts
    voice.js        — TTS request/playback via /api/tts tokens + optional browser STT (mic capture is client-side per design)
    orb.js + floating.js + gestures.js + shortcuts.js — chrome
    welcome.js      — first-run overlay
    modes/{chatws,coding,research,trading,vision,automation,phone}.js — per-workspace renderers
```

Truthfulness of displayed state: everything except workspace-mode *suggestions* is **real runtime state** — `core_state` mirrors actual pipeline stages, `agents` events mirror the exact dict in `ZerionUISession._agents`, metrics are sampled host stats, phone_state events come from PhoneBodyManager.snapshot. Trading workspace is data-inert (arch_map explicitly marks `finance/subsystem MISSING: no trading engine exists in the Core; UI trading panel is inert-unless-data and never fabricates`). Vision workspace does not fabricate OCR results (`vision/ocr_objects MISSING` per GAP_MATRIX). This matches the "no fake buttons" standing rule.

---

## 17. API REALITY MAP (every route, verified by connectivity_audit §8)

| METHOD | PATH | Handler | Auth | Service/Core touched | Purpose | Test |
|---|---|---|---|---|---|---|
| GET | `/` | index | none | static FileResponse | SPA shell | smoke |
| GET | `/health` | health | none | — | liveness | test_ui_bridge, second_audit |
| WS  | `/ws` | websocket_endpoint | none | full session pipeline | primary realtime channel | smoke + test_ui_bridge |
| GET | `/api/bootstrap` | api_bootstrap | none | tool_manager.list_tools, VERSION file, config snapshot | hello payload mirror | ui tests |
| GET | `/api/status` | api_status | none | session.snapshot + latest_metrics + heartbeat.json if service-hosted | System panel | ui tests |
| GET | `/api/memory` | api_memory | none | load_memory + config.MEMORY_PATH (sanitized ~) | Memory Inspector | ui tests |
| GET | `/api/knowledge` | api_knowledge | none | session.knowledge.db.query (limit-clamped 1-200) | Research/Memory view | ui tests |
| GET | `/api/logs` | api_logs | none | bus.replay filtered (limit-clamped 1-600) | Logs panel | ui tests |
| GET | `/api/fs/list` | api_fs_list | none | **tool_manager.execute('list_directory')** | Explorer | ui tests |
| GET | `/api/fs/read` | api_fs_read | none | **tool_manager.execute('read_file')** (200KB cap) | Explorer | ui tests |
| GET | `/api/settings` | api_settings_get | none | config attrs | Settings panel | ui tests |
| POST | `/api/settings` | api_settings_set | none | whitelisted 4 keys (PLANNER_ENABLED, ENABLE_SELF_CRITIC, VOICE_ENABLED, LOW_CONFIDENCE_THRESHOLD) + best-effort .env persist | live toggles | ui tests |
| GET | `/api/phone/state` | api_phone_state | none | PhoneIntelligence().body.snapshot (lazy singleton on app.state) | Phone layout | ui tests |
| GET | `/api/phone/action/{id}` | api_phone_action | none | body.action(id) read-only | Phone layout detail | ui tests |
| GET | `/api/tts/{token}` | api_tts_audio | none (expiring token) | TtsService.resolve → FileResponse from speech cache | TTS audio delivery | test_voice_service |
| GET | `/static/*` | StaticFiles mount | none | — | assets | smoke |

WS message types client→server: `message, confirm, cancel, terminal, tts, image, ping, replay` — all handled in `_handle_client_message` (ui/server.py:285-344), and connectivity_audit asserted server handles every type the client emits + client subscribes to every critical event.

---

## 18. FILE-LEVEL DEPENDENCY GRAPH (critical set)

```
main.py
 ├─ config
 ├─ core.logging                            # leveled tee
 ├─ llm ── api ── providers.router ── providers.gemini ── requests ── GeminiHTTPS
 │    └─ tools.manager(list_tools for prompt)          [llm.py:141]
 │    └─ cognition.context.assemble                    [llm.py:156]
 ├─ knowledge.manager ── knowledge.{database,search,ranking}
 ├─ learning.{engine → experience,reflection → knowledge.manager; background → optimizer → knowledge.database}
 ├─ cognition.{engine → constitution.policy + curiosity + personality; reasoning → knowledge.manager}
 ├─ capabilities.evolution ── capabilities.{manager,reasoning} ── knowledge.manager
 ├─ constitution.constitution  (startup verify)
 ├─ intelligence.runtime ── intelligence.{world,composition,projects,simulation,quality,experience,reflection,models,registry,resolver} + memory.intelligence
 ├─ intelligence.critic(self_critic) ── knowledge.manager(learning records)
 ├─ phone.engine ── phone.{discovery,controllers,extract,dispatch,models,verifier,manager,actions,state,audit} ── constitution.policy + learning.engine + intelligence.{experience,reflection,world,projects}
 ├─ speech (TTS status/speak — thread-spawned, never blocking the loop)
 ├─ tools.manager ── tools.registry(discover) ── tools.{17 modules} ── constitution.policy(gate)
 ├─ planner.planner ── planner.{context,decomposer(llm for decomposition),executor(tool_manager),goal,state,verifier,workflow,ranking,models}
 ├─ intent.{commands, engine, models} ── intent.{classifier, fast_planner→meta+tools.manager, history, session_state}
 └─ core.turn_pipeline

ui/server.py ── starlette(Starlette, FileResponse, JSONResponse, Route, WebSocketRoute, StaticFiles) + uvicorn
 ├─ config, constitution.constitution, core.logging, speech, tools.manager
 ├─ ui.events(bus) ── asyncio queues + thread-safe emit
 ├─ ui.metrics(sample) ── psutil?/procfs
 ├─ ui.session(ZerionUISession) ── main(SessionMemory, minimal_memory_for_prompt) + full engine stack above + ui.events
 └─ ui.tts(service) ── speech (Gemini TTS WAV) + token cache

runtime/__main__.py ── runtime.lockfile + runtime.service
runtime/service.py ── config + core.logging + runtime.{greeting,rcfg,health,lockfile,logging}
   lazy-on-stage: constitution, tools.manager, speech, uvicorn+ui.server(thread), memory.memory_manager, knowledge.database, learning.{optimizer,retention,background}, phone.discovery, agents.service   ← NOTE: 'agents' probe → ImportError (alias)
agents/{service→pool→tools.manager+knowledge.manager(direct query lane), orchestrator→agents.{pool,types,messages}+intelligence.critic+knowledge.manager, types, messages}
evolution/* ── testing.runner + constitution (owner flow only)
learning/{controller→acquisition,curriculum,practice,errors,progress,retention,transfer,meta,verification→knowledge.manager} — reachable only via tools/learning_tools.py
```

All draws above are IMPORT edges verified by AST scan (this session) — call edges were traced in Sections 3-4.

---

## 19. CIRCULAR DEPENDENCIES (static, AST-derived, mission: report only)

Cycles detected at top-level namespace (import-graph closure):

```
memory → intelligence → memory        (memory/intelligence.py imports intelligence.world; intelligence/runtime.py imports memory.intelligence — function-local imports break it at runtime)
tools → agents → tools                (tools/agent_tools imports agents.service; agents/pool imports tools.manager — different modules, both exist; no ImportError observed because pool imports manager, agent_tools imports service; they never cross-import in one linear chain)
runtime → ui → runtime                (runtime/service lazy-imports ui.server; ui/server lazy-imports runtime.greeting inside lifespan — both function-scoped: no import-time cycle)
intent → benchmarks → intent          (intent/commands.py imports benchmarks lazily inside /benchmark handler)
runtime → ui → main → runtime         (ui.session imports main classes at module scope BUT runtime.service does not import main)
ui → main → ui                        (ui.server imports ui.session → main; main imports ui.server only inside _run_ui try-block at call time)
```

**Runtime impact today: none observed** — every cycle edge crosses either a function-local import or an asymmetric pair (different submodules). Fresh-process boots succeed (all three entry paths executed in this sandbox), and `second_audit` "every module imports (0 failures)" passes. **Severity: LOW** — fragility risk if anyone moves these function-local imports to module scope. No fix applied (mapping only).

---

## 20. DUPLICATE SYSTEMS (real duplicates, and which is live)

| Concern | Impl A | Impl B | Live one & why |
|---|---|---|---|
| Conversation turn | main.py:run_loop | ui/session.py:_run_turn | **BOTH, intentionally** — ui/session mirrors main line-for-line by explicit invariant; shared primitives (`SessionMemory`, `minimal_memory_for_prompt`, `core/turn_pipeline`) prevent drift |
| Startup greeting | main._run_legacy_terminal (blocking=False) | ui/server.lifespan._startup_greeting + runtime.greeting once-guard | All three paths deliberate; `SUPPRESS_STARTUP_GREETING` flag ensures exactly-one delivery per process |
| Health monitoring | runtime/health.py | ui/metrics.py | Different scopes: service probes vs UI telemetry — no duplication of function, only of concept |
| Memory | memory/memory_manager (JSON persona) | memory/long_term + memory/intelligence (knowledge-backed) | Both live and documented: JSON = assistant persona surface, SQLite = operational knowledge/experience |
| Logging | core/logging.py | runtime/logging.py (JSONL) | core logging = human console + bus tee; runtime logging = structured service journal; service uses runtime/logging, front ends use core/logging |
| Agent singleton alias | agents/service.py exports `pool`; agents/__init__.py re-exports as `agent_pool` | — | Single instance; two names ⇒ caused the agents-probe bug (Section 5) |
| Evolution "deploy" gates | constitution/evolution.py | tools/manager policy | ProtectedEvolution is the *owner-flow* wrapper; tool policy is the *per-turn* gate — complementary, not duplicated |

No duplicate API servers (Starlette only; FastAPI was removed in the Starlette port — `grep fastapi` returns zero hits in production code).

---

## 21. MODEL / LLM MAP (actual routing)

```
get_llm_output(user_text, memory_block, image_b64?, image_mime?)
  → system prompt: prompt.txt (verbatim; render_prompt is a no-op today — verified: prompt.txt has no {{tokens}})
  → user prompt: user_text + assemble(memory_block) [bounded relevance-ordered] + tools block (41 descriptions)
  → api.call_llm → providers.router.call_llm(provider_name=None)
  → router: provider_name must be None or 'gemini' else ProviderError
  → GeminiProvider (lazy singleton)
       is_configured? bool(GEMINI_API_KEY)
       preflight: socket.create_connection(generativelanguage.googleapis.com:443, timeout≤3s)
       POST config.GEMINI_URL (f"…/models/{GEMINI_MODEL}:generateContent", default gemini-3-flash-lite)
       payload: system_instruction + user parts; image → inline_data.insert(0)
       generationConfig: temperature 0.2, maxOutputTokens 500
       retries: 429/5xx up to 2 retries, honors Retry-After (≤5s), backoff 0.5s+
       timeout: config.REQUEST_TIMEOUT (30s default)
       error mapping: 401/403 → key invalid; parse shape → ProviderError with first 200 chars
  → safe_json_parse → {intent, parameters, text, memory_update, needs_clarification}
  → plain-text fallback (memory_update unavailable that turn)
```

- **Streaming**: NOT implemented (single POST, one-shot response).
- **Tool calling**: NOT function-calling protocol — the model emits `intent:<tool-name>` inside the JSON contract and the Tool Manager dispatches. Deterministic, model-agnostic.
- **Structured output**: prompt-driven JSON + defensive parser; no response_schema/mime config sent.
- **Context limits**: none enforced against token count — bounding is by construction (memory reducer + 5-record retrieval + 5-history + small tools block), not by tokenization.
- **TTS model**: `GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts` via speech.py; streaming conversions to cached WAV; local player exec path on device; UI plays via /api/tts.

---

## 22. EXTERNAL DEPENDENCY MAP

| Dependency | Required for | Optional? | Breaks without it | Offline? |
|---|---|---|---|---|
| Python ≥3.10 | everything | no | — | yes |
| `requests` | Gemini/TTS HTTP | **yes at runtime** — core turns degrade gracefully (`AI ERROR…reaching the AI provider.`) | LLM, TTS, http_get/http_post tools, download_file | Partial (request-grade only) |
| `python-dotenv` | .env loading | yes | falls back to real env vars | yes |
| `starlette` + `uvicorn` | Web UI | yes for UI; `--terminal` works without | UI entry auto-falls back to REPL with printed hint | yes |
| `psutil` | metrics richness, agent capacity RAM bound, system tools | yes everywhere | /proc fallbacks engage (ui/metrics.py:44+, agents/pool.py:53+, system tools) | yes |
| SQLite3 (stdlib) + FTS5 | knowledge DB | FTS5 optional (virtual table creation failure tolerated) | none （核心区以外 graceful) | yes |
| `play-audio`/`termux-media-player`/`mpv` | TTS playback on device | yes | `speak()` no-ops with status logging | yes |
| `termux-*` binaries | phone controllers | yes | per-controller `available()` false → honest "not available" | n/a (device-only) |
| `jsdom` | dev smoke only | yes | — | dev only |
| Gemini API + key | all LLM/TTS | required for intelligence | offline turns run all local machinery (classifier, fast tools, memory, phone gating) and reply with explicit errors | NO for LLM/TTS |
| pytest | tests + `run_pytest` tool | yes | tool unavailable → honest response | yes |

No Docker/systemd requirement: autostart files are generated only on explicit `--install-autostart --yes`.

---

## 23. ERROR PATH MAP (critical failure points & recovery)

| Subsystem | Failure point | Handler | Recovery | Final failure | Logging |
|---|---|---|---|---|---|
| LLM call | network/key/parse | `except Exception → log.error + _fallback("…reaching the AI provider.")` (llm.py:178-181) | user sees explicit error next turn | response = fallback string, turn continues | console + bus 'log' |
| Self-critic | any exception | try/except → "self-critic deferred" note (main.py:428, session.py:736-738) | original response used | none | print/log |
| Memory write | corrupt on read | auto fallback to .bak w/ warning (memory_manager.py:88) | 1-gen backup | empty structure + loud warning | log.warning |
| Knowledge DB | any query exception in UI endpoints | `return None → records: []` (api_knowledge) | — | empty list (no 500) | — |
| Tool exec | any exception | caught → ToolResult.fail("execution_failed") (manager.py:104) | message rendered to user | none | tool end event w/ error |
| Tool availability check | raises | treated unavailable (manager.py:48-50) | — | "couldn't check" message | — |
| Planner | exceptions inside handle_request | caught → fall back to normal chat (main.py:386, session.py:700) | chat path continues | none | print/bus log |
| Phone dispatch | KeyError/ValueError in _call | caught → "Invalid phone request: …" (dispatch.py:19) | verification still runs on the failure | ActionResult(False) | audit.jsonl + experience records |
| WS handler | unexpected exception | logged + bus 'log' ERROR, connection kept alive attempt (server.py:244-249) | finally-unsubscribe cleans up | that client drops | core_log.error |
| TTS | generation exception | state:'error' envelope with reason | browser fallback offered by client on 'browser_fallback'/'unavailable' | text-only reply | tts internal counters |
| Service supervisor | subsystem fail | backoff per subsystem; critical(core) FAILED → clean shutdown | recover hooks (api/voice/workers) | EXIT_CRITICAL_FAILURE=4 | service.log.jsonl |
| Learning capture | any exception | "learning deferred: …" (main.py:441) | turn unaffected | none | print |
| Idle maintenance | load/no-space/exception | BackgroundLearning.run_once returns string reason; never raises | next tick retries | none | debug log |

---

## 24. TEST REALITY MAP (what tests actually execute)

`pytest tests/ -q` → **233 passed in 10.29s** (this run). Coverage claims mapped to actual exercised surfaces:

| Test file | Actually exercises | Type |
|---|---|---|
| test_core_stabilization.py | memory atomic save/load/corrupt-recovery, config parse warnings, prompt load failure path | unit+runtime |
| test_entrypoint.py | main.py --help/UI fallback paths, single guarded entries | runtime (subprocess) |
| test_main_integration.py | run_loop sequence through mocked ui; end-to-end happy & edge paths incl. confirmations | integration |
| test_runtime_pipeline.py | same turn contract for UI session + turn_pipeline text invariance | integration |
| test_final_e2e.py | full chat turn + tool + planner pause + resume through both front ends | E2E |
| test_final_features.py | current feature battery incl. critic gating | integration |
| test_gemini_*.py (4 files) | provider transport (mocked HTTP), retries/error mapping, image kwarg contract, voice TTS generation envelope | unit+integration |
| test_self_critic.py | review/improve logic incl. confidence threshold + loop-cap | unit |
| test_intelligence.py | runtime intelligence prepare/complete, world/projects/quality stores | unit+integration |
| test_memory_intelligence.py | memory/intelligence record+retrieve | unit |
| test_reasoning.py / test_cognition_influence.py | reasoning scaffolding + decisions/persona influence | unit+integration |
| test_constitution_engine.py + test_constitutional.py | lock verify, tamper abort, ProtectedEvolution gates | unit+integration |
| test_execution_safety.py | destructive tool confirmation flow + constitution_denied | unit |
| test_hardening.py | misc fuzz/safety invariants | unit |
| test_integration_map.py | cross-module wiring assertions (e.g. session mirrors main) | static+runtime |
| test_learning_system.py | LearningController loop (acquire→practice→verify→generalize) | integration |
| test_orchestrator.py | classify/spawn/aggregate/critic/telemetry incl. `agent_pool` alias (via `agents` package — **not** via `agents.service`, which is why the service-probe typo survives) | unit+integration |
| test_phone*.py (4 files) | extractor/dispatch/manager/state/audit, controllers mocked where binaries absent | unit+integration |
| test_runtime.py + test_runtime_integration.py | service lifecycle: lock, stages, probes (phone env-gated, voice degrade), heartbeat, UI-in-service /health 200 | integration |
| test_setup.py | installer layers + relock flow | integration |
| test_ui_bridge.py | REST/WS against real ASGI app (TestClient/ASGITransport) | E2E |
| test_voice_service.py | tts service states (ready/dedupe/ratelimit/expiry/secret-free/token-safety) | unit+integration |
| test_world_class.py | decisions/context/meta/benchmarks + verifier lane | unit+integration |

**Not covered by tests (by inspection):** `runtime/service.py:462` probe-internal typo (probes swallow exceptions on purpose, so no assert catches the missing name — the DEGRADED state is only visible at runtime, as this map captures); real Gemini bytes over the wire; TTS playback to hardware; multi-day soak.

---

## 25. REALITY vs EXPECTED — MASTER GAP TABLE

Derived *after* mapping. "Desired" comes from repo docs (README/FINAL_RELEASE/INTELLIGENCE_SYSTEMS) and the mission's own Zerion vocabulary.

| Desired capability | Actual implementation | Runtime status | Missing link | Severity |
|---|---|---|---|---|
| Single adaptive AI OS, UI-first | main.py default → ui/server | LIVE | — | — |
| 24/7 supervised service | runtime/service.py + health/gates | LIVE (probed) | **agents-probe ImportError → agents subsystem permanently DEGRADED in health telemetry** | MEDIUM (telemetry-only; conversation path unaffected) |
| Canonical multi-agent orchestration | agents/* + orchestrator + tool bridge | REGISTERED_NOT_EXECUTED (works, model-invoked only) | no automatic "complex goal → orchestrator" escalation hook from intent/classifier (planner path covers multi-step instead) | LOW (by design per module docstring "anti over-engineering") |
| Self-evolution | evolution/* + ProtectedEvolution | DEFINED_NOT_EXECUTED | no runtime trigger; owner-only by constitution (documented architectural stance, NOT a bug) | LOW |
| Universal self-teaching | learning/controller full loop | REGISTERED_NOT_EXECUTED (model-invoked `learn_domain` only) | no idle/auto curriculum trigger (idle path only consolidates) | LOW-MEDIUM (docs "learning controller" expectation vs tool-mediated reality) |
| Real Gemini conversation | providers/gemini + llm | PARTIALLY_LIVE (end-to-end logic verified; bytes-on-wire need key) | environment (`GEMINI_API_KEY`) | ENV-GATED |
| Gemini TTS to phone speaker | speech.py + ui/tts.py | PARTIALLY_LIVE | sandbox has no key/no player; Termux transcript earlier session proved voice-ready message | ENV-GATED |
| Phone body control | phone/* stack through body.manager | PARTIALLY_LIVE | Termux/`termux-api` binaries; SMS/telephony/camera unverifiable off-device | ENV-GATED |
| Multimodal vision | image WS → session.process_image → provider inline_data | PARTIALLY_LIVE | keyed multimodal round-trip unverified here | ENV-GATED |
| Browser-side STT | ui/static/js/modules/voice.js | PARTIALLY_LIVE (by design; server-side STT intentionally absent) | — (documented) | LOW |
| Finance/trading core | not implemented | MISSING (honest GAP_MATRIX) | engine does not exist; UI inert-unless-data | DOCUMENTED OPEN |
| OCR/object detection | not implemented in core | MISSING (honest GAP_MATRIX) | no OCR multimodal pipeline | DOCUMENTED OPEN |
| Process sandboxing for run_python/run_shell | confirmation-gated host exec only | PARTIAL security posture | no jail/containment — stated honestly | MEDIUM (accepted risk posture) |
| Memory leak detection / reconnect limiting | not implemented | MISSING | no module | LOW (observability depth) |
| Setup bootstrap | setup.py layered + relock | LIVE | — | — |

---

## 26. CONFIDENCE MAP (high/med/low for major conclusions)

| Conclusion | Confidence | Grounding |
|---|---|---|
| main.py is the authoritative single production entry; UI default | HIGH | code + second_audit + fresh help-boot run |
| ui/session mirrors main turn pipeline | HIGH | line-level read of both, plus test_integration_map |
| 41 tools discoverable + live chain | HIGH | direct `list_tools()` execution (this session) |
| Gemini-only transport with retries + error contract | HIGH | code + 4 gemini test files + ProviderError reproduced live |
| Memory dual-store (JSON + SQLite) with atomic guarantees | HIGH | code + stabilization tests |
| Constitution participation in runtime decisions | HIGH (policy gate), HIGH (startup integrity), TEST_ONLY (deploy path) — as split above |
| Agents subsystems functional but passive | HIGH (tests + spawn probe) / HIGH (no proactive caller — grep of all callers) |
| Agents health probe BROKEN in service | HIGH (executed snapshot this session, exact ImportError captured) |
| ui/tts.py debug-print debris present | HIGH (four lines shown; fires per request in code path) |
| Circular imports | HIGH static existence / HIGH no runtime impact today (all entries booted) |
| TTS-to-speaker and keyed LLM on hardware | LOW in sandbox (ENV-GATED; previous session's Termux transcript is MEDIUM-level external evidence) |
| Phone SMS/camera/torch on real device | LOW (no device available) |
| Long-horizon 24/7 stability (days) | LOW (not soaked here) |

---

## 27. MASTER COMPONENT TABLE (summary per §33)

| Component | Location | Type | Used by | Calls | Runtime | Evidence | Status |
|---|---|---|---|---|---|---|---|
| Entry:UI | main.py | entry | user/supervisor | ui.server, ConstitutionEngine | process | help-run + audits | LIVE |
| Entry:terminal | main.py | entry | user | run_loop engines | process | audits + Termux transcript | LIVE |
| Entry:service | runtime/ | entry+dæmon | supervisor | ui.server(thread), monitors | process | sandbox probe | LIVE |
| Turn pipeline | core/turn_pipeline.py | shared lib | main, ui.session | — | per turn | tests | LIVE |
| Config | config.py | settings | all | env | per turn | live warnings | LIVE |
| LLM transport | providers/ + api.py + llm.py | service | both front ends | HTTPS | per LLM turn | tests + ProviderError live | PARTIALLY_LIVE (env key) |
| Intent engine | intent/ | pipeline stage | both | classify, fast tools, meta | per turn | tests + smoke | LIVE |
| Meta-intelligence | meta.py | responder | fast_planner | registries/knowledge | on question | tests | LIVE |
| Planner | planner/ | service | both (gated) | decomposer(LLM), executor(tools) | gated turns | tests | PARTIALLY_LIVE |
| Self-critic | intelligence/critic.py | pipeline stage | both | 1 LLM call max/turn | chat turns | tests + Termux transcript | LIVE |
| Memory JSON | memory/memory_manager.py | store | both | fs | per turn | tests | LIVE |
| Memory LTM/intel | memory/{long_term,intelligence}.py | store adapters | intelligence.runtime, phone | KnowledgeManager | per turn | tests | LIVE |
| Knowledge DB | knowledge/ | store | ~10 subsystems | sqlite3+FTS5 | per turn | sandbox query | LIVE |
| Learning eng/bg | learning/{engine,background,...} | service | both | KM stores | per turn/idle | tests | LIVE |
| Learning ctrl | learning/controller.py +8 | service | learn_domain tool only | full loop | on tool | tests | REGISTERED_NOT_EXECUTED |
| Tool manager | tools/manager.py+registry.py+base.py | dispatcher | all pipelines incl. UI REST | Tool.execute | per tool call | 41 tools enumerated | LIVE |
| 41 tools | tools/*.py | capability | LLM/fast planner/agents/UI panels | os/net/fs/subproc | per call | enumerated | LIVE |
| Constitution integrity | constitution/constitution.py | gate | all entries | sha256 verify | startup | live | LIVE |
| Constitution policy | constitution/policy.py | gate | tools, phone, cognition prepare | evaluate | per consequential dispatch | tests + code | LIVE |
| Agents pool | agents/{service,pool}.py | service | agent_* tools, benchmarks | threads/KM/tools | on demand | spawn probe | REGISTERED_NOT_EXECUTED |
| Orchestrator | agents/orchestrator.py | service | agent_orchestrate tool | lanes+critic+KM | on demand | tests | REGISTERED_NOT_EXECUTED |
| Phone stack | phone/ | body layer | both, /api/phone/* | termux bins | per phone intent | tests + Termux transcript | PARTIALLY_LIVE |
| Runtime health | runtime/health.py | service | service | probes | 15s cadence | live snapshot | LIVE (1 probe BROKEN) |
| Lockfile/log/autostart | runtime/{lockfile,logging,autostart}.py | service | service, CLI | fs | on start | tests | LIVE |
| UI server | ui/server.py | API+WS host | browser | session, bus, tts | process | tests + audits | LIVE |
| UI session | ui/session.py | adapter | server | full engine stack | per turn | tests | LIVE |
| UI bus/metrics/tts | ui/{events,metrics,tts}.py | service | server/clients | asyncio/threads | continuous | tests | LIVE |
| Static SPA | ui/static/*/ *.js/css/html | client | browser | WS+REST | continuous | smoke 70/70 | LIVE |
| Evolution engine | evolution/ + constitution/evolution.py | service | owner only (setup) | staging/tests | never at runtime | tests | DEFINED_NOT_EXECUTED |
| Test runner svc | testing/runner.py | service | evolution | pytest subprocess | never at runtime | tests | TEST_ONLY |
| Audits/arch/gap | second_audit, connectivity_audit, arch_map | dev tooling | owner | everything | on demand | green today | TEST_ONLY |
| Benchmarks | benchmarks.py | harness | /benchmark cmd | cognition/agents sample | on demand | unit-tested | TEST_ONLY |
| Personality | personality.py | modulator | cognition.engine | memory prefs | per turn | tests | LIVE |
| Speech | speech.py + ui/tts.py | voice | both (terminal), UI WS | Gemini TTS+player | per reply (enabled) | envelope tests; audio NOT VERIFIED | PARTIALLY_LIVE |
| Meta-answer self-audit | meta.py | (dup row — see Meta-intelligence) | | | | | |
| Session state snapshot | intent/session_state.py | read-only | /api/status | engine reads | on demand | tests | LIVE |

---

## 27b. REMEDIATION UPDATE (integration pass, 2026-08-08 — same day as mapping)

Changes applied (every item runtime-verified; full battery: **253/253 pytest** incl. 20 new integration tests, 22/22 second audit, 45/45 connectivity, 70/70 UI smoke, arch_map 49/43 unchanged):

- **P0-1 agents probe** — `runtime/service.py:462` now `from agents import agent_pool` (the documented public package surface; same import shape as `connectivity_audit.py:429` and `tests/test_orchestrator.py:104`). Probe: `agents → healthy, last_error=None`.
- **P0-2 tts debris** — four stderr prints → two `log.debug` lines on the `core.logging` channel; zero raw stderr in request path (test-covered).
- **Agent runtime integration** — `intent/engine.py:process` now consults `agents/orchestrator` after the fast planner for CHAT requests covering ≥2 specialist domains. Engagement gates: ORCHESTRATION_ENABLED (new config/env + UI settings toggle), Intent.CHAT only, evidence whitelist (knowledge/long_term layers only; capability/critique/reflection/error-memory echo layers and knowledge_gap question-records excluded — proven to defeat the self-echo feedback loop), ≥50% topic-token coverage, critic accept required for direct answers (revise → injected as explicitly-uncertain `orchestrated_evidence` context instead). Orchestrator lanes now fan out in parallel under one 20s deadline with one bounded restart for transient failures, and every lane returns the full result contract (task_id/agent/objective/result/evidence/confidence/error/tools_used/duration_s/verification_status/restarted).
- **Learning controller activation** — new `learning/triggers.py` gate inside the engine: explicit `learn <topic>` / `teach yourself <topic>` runs the canonical `LearningController` offline; repeated tool failure (≥3 same-tool failures in session) surfaces a structured log signal (never auto-studies). `/learn <topic>` added to the command palette routing through the existing `learn_domain` tool. Retention due-count now reported by idle maintenance (`BackgroundLearning.run_once`); error memory records key on concept and are retrievable via the standard search path (wide-window filter fix); the self-critic flags >80-char stored summaries below confidence threshold as `critic-flagged` instead of silently promoting them; curriculum `prerequisite_of`/`part_of` edges are written into the existing `intelligence/world` graph_edges table and consulted on failure.
- **Real bugs found & fixed by the new E2E test**: `learning/errors.py` crashed on int failure payloads (learn-from-failure path was unreachable); controller generalization probes reused identical seeds for back-to-back runs (run_id salt added — "unseen" is now true).

Still open (unchanged, by design/environment): evolution DEFINED_NOT_EXECUTED at runtime (constitutional stance), STT browser-side only, Gemini LLM/TTS bytes and phone hardware rows ENV-GATED, finance/OCR documented MISSING, confirmation-only sandboxing posture.

## 27c. COMMUNICATION LAYER UPDATE (2026-08-08, same-day continuation)

New subsystem `comms/` (16 modules) + 9 tools + 6 UI endpoints + workflow engine.
Updates to the map's subsystem table:

| Component | Status | Evidence |
|---|---|---|
| comms/ unified layer (inbox/classify/reply/approvals/rails/audit/verify/engine) | LIVE | tests/test_communication_layer.py 53 tests green incl. 4 E2E chains |
| email connector (IMAP/SMTP stdlib) | PARTIALLY_LIVE (transport-injected tests verified; live mailbox NOT VERIFIED — needs authorized account) | test fakes + honest disconnected state |
| telegram connector (Bot API) | PARTIALLY_LIVE (same rule) | injected-http E2E |
| phone/social notification intake | PARTIALLY_LIVE (termux-notification-list gated; sandbox shows disconnected, honestly) | FakeAdapter tests + live probe |
| contacts / calendar (local authoritative) | LIVE (local tables work offline, conflicts/availability computed) | calendar math tests |
| workflow engine + scheduler | LIVE (service maintenance trigger pump; manual runs via workflow_run) | workflow tests incl. failure→error-memory |
| UI Communication panel | LIVE | 6 endpoints 200 on live boot; smoke 70/70 |

Approval ladder defaults to LEVEL 2 (confirm before send); high-risk markers
force confirmation even on trusted rules; audit never stores secrets.

## 27d. BACKGROUND AUTONOMY UPDATE (2026-08-08, same-day continuation)

| Component | Status | Evidence |
|---|---|---|
| autopilot event spine (dedupe→loop guard→classify→state→firewall→draft→gate→send/park/pause→verify→learn) | LIVE (sandbox: connectors unconfigured → idle quiet; faked transports drive full flows) | tests/test_autopilot.py 32/32 |
| exactly-once event/action registry | LIVE | claim/settle + crash-reprocess tests |
| conversation isolation (platform+account+conversation) | LIVE | scope tests incl. wrong-recipient denial |
| firewall (injection/exfiltration/sensitive/links/dangerous-attach) | LIVE | quarantine-before-draft test incl. via tool surface |
| evidence gate (multi-dimensional autonomous|approval|pause|observe) | LIVE | decision matrix tests |
| offline outbox (TTL/backoff/stop-on-auth/permission/unknown + revalidation) | LIVE | outbox suite incl. stale-drop proof |
| loop guard (echo/bot-marker/cycle cooldown) | LIVE | loop suite |
| shadow mode + downgrade-only quality gates (no self-upgrade) | LIVE | quality/shadow tests; graduation = owner op |
| overrides incl. ESTOP (clears queue) | LIVE | live HTTP control-plane probe |
| 24/7 service pump + host-load degradation | LIVE | pump test + constrained-mode test |
| model/agent disagreement stop | LIVE (composition rule in decision gate) | decision test |

Remaining environmental rows unchanged (real Telegram/email accounts, Termux
notifications on-device, Android background-restart policy) — all gated
honestly and documented, none claimed.

## 27e. SERIOUS MODE + AUTHORIZED 24/7 UPDATE (2026-08-08, same-day)

| Component | Status | Evidence |
|---|---|---|
| multilingual semantic command routing (EN/AR/Darja) | LIVE | tests/test_serious_mode.py matrix + live WS run (Arabic flow cmd → ACTIVE) |
| Serious Mode auth (PBKDF2, lockout, count-only logging) | LIVE | auth tests incl. lockout-vs-correct-code, secrecy probes (memory/knowledge/audit/stdout never carry the code) |
| Strictest-policy interaction (serious ⇒ auto→confirm) | LIVE | decision-gate test both directions |
| Authorized background workflow objects (TTL, immediate stop) | LIVE | flow tests incl. expiry + stop-aborts-replies |
| COMM_REQUIRE_FLOW gate (no flow ⇒ observe-only) | LIVE | autopilot gate tests (before-after stop) |
| Constitution v1.1 (+17 laws COM/AUT/BGS) | LIVE | engine verify_lock, parse + enforcement-mapping tests |
| comm health heartbeat (service/listeners/queue/last_event/last_error) | LIVE | health snapshot writer + runtime probe read |
| UI: serious badge, bg flows with stop, control-plane ops | LIVE | live HTTP/WS probes |

Constitution, memory, learning, agents, tools, comms spine all unchanged in
shape — this pass added guarantees, not parallel systems.

## 27f. FINAL INTEGRATION + READINESS (2026-08-08, closing pass)

Verified facts:: readiness_audit.py recomputes everything each run — the
numbers belong to the code, not to this text.

| Delivery | Status | Evidence |
|---|---|---|
| Startup self-diagnostic (`runtime/selfcheck.py` + `runtime --check`) | LIVE | prints PASS/DEGRADED/… with real probes (14 rows) |
| Setup contract (PHONE_SETUP.md; extended setup.py) | LIVE (doc + installer verified in sandbox) | setup --check run |
| Machine system graph (SYSTEM_GRAPH.json, 365 nodes / 1068 edges) | LIVE | emission test inside readiness |
| Readiness scoring (evidence-weighted) | overall 92.0% READY-WITH-LIMITATIONS | READINESS_REPORT.json |
| Device-dependent rows (real soak, camera/telephony binaries, email/telegram live delivery) | UNVERIFIED (documented; never claimed) | readiness reports list them by name |

Nothing in this pass is cosmetic: every audit check calls the subsystem it
scores, and `READY`/`PHONE READY` claims stay withheld where the sandbox
has no phone.

## 28. FINAL SUMMARY (§38 contract)

**Actual Entry Point:** `main.py:main()` → Web UI default (`_run_ui` → uvicorn/hosting `ui.server.app`); `main.py --terminal` REPL; `python -m runtime` service supervising the same UI in a thread plus health maintenance.

**Actual Core:** One synchronous per-turn pipeline shared by both front ends (SessionMemory → memory/knowledge/cognition/capability/reasoning/runtime-intelligence context build → intent classify+fast planner → optional planner → single Gemini call → optional self-critic → memory/learning writes → tool or chat dispatch).

**Actual Conversation Path:** Browser→WS→`ZerionUISession._run_turn`→`llm.get_llm_output`→`api.call_llm`→`providers.router`→`GeminiProvider.call`→parse→critic→`update_memory`+`learn_task`→bus `chat` event→client.

**Actual Memory:** `memory/memory.json` (4-section persona JSON, atomic+bak) + `knowledge/zerion_knowledge.db` (SQLite WAL+FTS5) + in-process `SessionMemory` (5-turn window). No vector store.

**Actual Agent System:** `agents/` = 10-type registry + resource-bounded thread pool + deterministic orchestrator with critic pass and KM telemetry. **Invoked only via 4 tools** when the LLM selects them; no ambient agent activity.

**Actual Orchestrator:** `agents/orchestrator.py:Orchestrator` (singleton) — classify→lanes→aggregate→self_critic.review→telemetry. Layered *beneath* the constitution-gated Tool Manager; all agent lanes are read-only by whitelist.

**Actual Tool System:** 41 auto-discovered tools; `ToolManager` singleton with lazy pkgutil registry, availability checks, destructive→`Constitution().evaluate`→single-slot confirmation; exposed to the LLM as `intent`-based selection text block; also serves UI REST (fs list/read) so no bypass route exists.

**Actual Security:** startup SHA256 integrity gate (constitution + main.py protected), per-dispatch policy evaluation, human confirmation for consequential actions, secrets env-only, TTS token scoping, UI fs capped through Core tools. No authN/authZ model (single-user local stance); execution sandboxing = confirmation only.

**Actual Constitution:** `constitution.txt` (12+ law records, parsed regex), `ConstitutionEngine` (integrity+PROTECTED set), `Constitution` policy (`evaluate`) — the latter is the **runtime-active** one (tools + phone), the former gates startup and the owner-invoked evolution deploy.

**Actual Evolution:** Fully built, fully tested, **not executed by any shipped runtime entry**; reachable by owner flow (`setup.py`/ProtectedEvolution) and tests. Documented architectural choice (EVO-002).

**Actual Health:** `HealthMonitor` with probe/recover/backoff/budget/runaway-guard + 10 registered subsystems + heartbeat.json + JSONL service log + UI metrics loop. One real defect found: `agents` probe references a name that doesn't exist in `agents.service` → permanent DEGRADED for that one subsystem (no functional blast radius).

**Actual UI:** Single Starlette app serving vanilla-ES-module SPA (20 JS modules, 6 workspace modes), Ws-first with REST panel endpoints, all backend traffic through `ZerionUISession`/`tool_manager`; zero-fake-controls posture verified by audits (trading/OCR panels inert-unless-data).

**Actual API:** 1 WS + 16 REST routes (listed in §17), all consumed by the SPA, no auth, loopback-oriented, public-host flag only affects auto-open URL.

**Actual Models:** Gemini `gemini-3-flash-lite` (text, JSON-contract, one-shot, temp 0.2, ≤500 out tokens, 30s timeout, ≤2 retries w/ Retry-After) + Gemini `gemini-2.5-flash-preview-tts` (WAV cache, token-served). Transport verified; keyed byte-round-trip and device playback NOT VERIFIED in sandbox.

**LIVE:** main×2 paths, ui server/session/bus/metrics, runtime service supervisor, intent engine, meta, command palette, memory JSON+SQLite, knowledge retrieval/FTS, per-turn learning/capability/runtime-intel/self-critic, tool manager+41 tools, constitution startup+policy gates, phone extractor+dispatch+body+audit (controller-level), personality modulation, sessions snapshot, settings persistence, audits (static+runtime).

**PARTIALLY_LIVE:** planner (config-gated, tested), phone controllers (Termux-dependent), speech/TTS playback (key+player-dependent), LLM real round-trip (key-dependent), multimodal vision (key-dependent), agents/finance-CATEGORY map (documented partial), STT (browser-side by design).

**REGISTERED_NOT_EXECUTED:** agent pool+orchestrator in normal flow, LearningController self-teaching loop (reachable via `learn_domain` tool only).

**DEFINED_NOT_EXECUTED:** evolution engine at runtime (by constitution), server-side STT (none exists).

**DEAD:** none among production modules (demo script `tests/demo_self_teaching.py` is a test-side demo); entry-points audit found no dev-server sprawl.

**BROKEN:** `runtime/service.py:462` agents-probe ImportError (`agent_pool` vs `pool`); `ui/tts.py:81-93` debug-print debris (stderr noise, no functional break). No others found by any battery.

**UNKNOWN:** none remaining — every subsystem is classified.

**Most Important Runtime Path:** Browser WS `message` → `ZerionUISession._run_turn` → context build → intent engine → `get_llm_output` → Gemini → critic → memory/learning writes → `chat` event.

**Most Important Broken Connection:** service health `agents` probe → `agents.service.agent_pool` (alias defined only in `agents/__init__.py`). A one-line import fix, but mapping-only phase → left untouched.

**Most Important Architectural Risk:** confirmation-only sandboxing for `run_shell`/`run_python` + no process containment; plus static-only cycle clusters that future module-scope refactors could turn into import errors.

**Most Important Missing Capability:** autonomous/idle self-teaching trigger (LearningController + EvolutionEngine both complete but need a policy-gated scheduler hook — currently neither fires without model-owner invocation), and process-level execution sandboxing.

---

## 29. THE REAL ZERION MAP (consolidated)

```
                                  ┌─────────────────────────────────────────────────────────┐
                                  │  OWNER (human) — approvals, /commands, settings, relock │
                                  └───────────────┬───────────────────────────────┬─────────┘
                                                  │ confirm/ownership             │ relock/deploy (owner-only)
            ┌─────────────────────────────────────┼───────────────────────────────┼───────────────────────────┐
            │                                     │                               │                           │
     ┌──────▼──────┐  --terminal          ┌───────▼────────┐             ┌────────▼─────────┐        ┌────────▼──────────┐
     │ main.py     │ ───────────────────► │  ui/server.py  │ ──static──► │  Browser SPA     │        │  setup.py         │
     │ (default UI)│                      │  Starlette+uv  │             │  20 ES modules   │        │  +ProtectedEvolt. │
     └──────┬──────┘                      │  /api/*  /ws   │ ◄─events── │  WS /ws client   │        │  → evolution/*    │
            │                             └───────┬────────┘             └──────────────────┘        │  (staged, never   │
            │ python main.py                      │                                                  │   auto-deployed)  │
            │                             session=ZerionUISession()                                  └───────────────────┘
            │                                     │  (mirrors run_loop branch-for-branch)
            │                                     ▼
            │            ┌─────────────────────────────────────────────────────────────────────────┐
            │            │  SHARED TURN PIPELINE  (SessionMemory state, event/print surface swap) │
            │            │  interrupt→mute→phone-pending→phone-extract→commands→plan/tool-pending │
            │            │  →clarification→CONTEXT BUILD→INTENT(classify+fast/meta)→PLANNER?→LLM  │
            │            │  →SELF-CRITIC→MEMORY UPDATE→LEARNING/CAP/RUNTIME-INTEL→INTENT DISPATCH │
            │            └───────┬────────────┬────────────┬─────────────┬──────────────┬─────────┘
            │                    │            │            │             │              │
            │     ┌──────────────▼──┐  ┌──────▼──────┐  ┌──▼───────────┐ │ ┌────────────▼─────────┐
            │     │ memory.json     │  │ knowledge/  │  │ cognition/   │ │ │ llm.py→api→providers │
            │     │ atomic+bak      │  │ SQLite+FTS5 │  │ capabilities │ │ │ →Gemini HTTPS        │
            │     │ persona state   │  │ ranked retr.│  │ intelligence/│ │ │ (key-gated)          │
            │     └─────────────────┘  └──────▲──────┘  │ runtime      │ │ └──────────▲───────────┘
            │                                 │         └──────┬───────┘ │            │ JSON contract
            │            ┌────────────────────┤                │         │   {intent,params,text,…}
            │            │ writers/turn: learn│_task            │ prompt  │            │
            │            │ cap.learn rtintel. │complete          │ fields  │            ▼ non-chat intent
            │            │ phone journal      │                 │         │   ┌──────────────────┐
            │            │ orch telemetry     │                 │         │   │ tools.manager    │
            │            │ idle consolidate   │                 │         │   │ registry(41)     │
            │            └────────────────────┘                 │         │   │ policy gate ◄────┼── Constitution.evaluate
            │                                                   │         │   │ confirm slot     │
            │     ┌───────────────┐  agents (tools-mediated)    │         │   └───┬──────────────┘
            │     │ phone/        │  ┌──────────────────┐       │         │       │ ToolResult
            │     │ extractor→body│  │ agents.pool      │       │         │       ▼
            │     │ manager→dispt.│  │  spawn lanes     │       │         │   41 tools incl:
            │     │  (policy gate,│  │  (KM | whitelisted│      │         │   file/exec/net/sys/
            │     │   verify,audit│  │   tools lanes)   │◄──────┼─────────┼───agent_delegate
            │     │   +intelligence│ │ orchestrator.run │ query/ │         │   learn_domain → learning/
            │     │   journal)    │  │ →KM telemetry    │ tool   │         │   controller (full loop)
            │     └──────▲────────┘  └──────────────────┘ lanes  │         │   skill_route → skills/manager
            │            │ termux binaries                       │         │   run_pytest → testing/runner
            │     ┌──────┴────────┐                              │         │
            │     │ Termux device │  (binary-checked; unverified │         │
            │     │ (off-sandbox) │   in this sandbox)           │         │
            │     └───────────────┘                              │         │
            │                                                    │         │
            │     ┌──────────────────────────────────────────────┴─────────┴───────────────────┐
            │     │ runtime/ ZerionService (python -m runtime) — hosts ui.server in a thread   │
            │     │ lockfile → core stage → ui thread → probes(core/api/mem/know/learn/phone/  │
            │     │ voice/model/workers/*agents*) → READY+greeting → Event-loop supervise:     │
            │     │ health 15s | heartbeat 5s | maintenance 900s | structured JSONL | SIGTERM  │
            │     │ *agents probe = DEGRADED (ImportError agent_pool) — ONLY broken row        │
            │     └────────────────────────────────────────────────────────────────────────────┘
            │
   voice: speech.py Gemini TTS WAV → device player (Termux)  |  ui/tts token endpoints (/api/tts) → browser
   evolution: DEFINED_NOT_EXECUTED at runtime (staged owner flow only)
   learning controller: REGISTERED_NOT_EXECUTED (tool-triggered self-teaching loop)
   agents: REGISTERED_NOT_EXECUTED in ambient flow (LLM-triggered lanes, whitelisted read-only)
```

— END OF MAP (no fixes applied; second-validation batteries remain green; one probe defect + debug-print debris reported verbatim) —

## 27g. REPAIR-MISSION CLOSE-OUT (2026-08-09)

Re-verified, already-correct rows: agent probe (canonical alias), tts debug
prints (absent). New since: auto planner escalation (default), evidence-based
plan completion, hardened exec containment, memory coordinator (single write
policy), gemini_health tool, 24/7 resource probe + agent reaper + 3000-tick
soak test (runaway guard proven). Suite 401/401; readiness_audit.computed
92.3% READY-WITH-LIMITATIONS; phone/device rows remain UNVERIFIED itemized.


## 27h. ARCHITECTURE COMPLETION (2026-08-09)

New subsystems (all runtime-proven by tests/test_architecture_migration.py):
core/bootstrap (one startup for both entries), core/events (internal bus),
core/state_manager (assembly on owners), core/workflow_orchestrator (owns
route consults), agents/engine (lifecycle+registry+plugins), mcp/* (gateway
+ 5 real adapters + policy + audit). Agent lanes route through the gateway;
main.py untouched in behavior (bootstrap call, protected-lock re-anchored).
