# Changelog

## 2.1.0 — Two-gap closure (engine-owned agents + canonical turn lifecycle)

Both gaps from the read-only completeness pass closed and verified; process
(to-long-explain-safely) and evidence are below.

**Gap 1 — Agent Engine bypass.** The single lifecycle authority is now
agents/engine.py and every producer drives through it:
  - agents/orchestrator.py lanes use self.pool.spawn → that pool attribute is
    the engine (constructor upgraded to route default + wrap a raw pool when
    a test injects one — old tests unchanged and passing)
  - tools/agent_tools.py spawns via engine.spawn (adds lifecycle events)
  - comms/workflow call_agent via engine.spawn
  - engine exposes wait/restart/stats/reap passthroughs and its OWN pool
    remains `agents.service.pool` (single source). The remaining
    pool-direct calls are the adapter layer itself (engine→pool) + the pool's
    own internal delegate/restart usage — classified ALLOWED INTERNAL USE.

**Gap 2 — canonical turn lifecycle.** New `core/turn_runner.TurnRunner(state,
engines, sink)` now owns the previously-duplicated branch chain
(interrupt→mute→phone→phone-missing→palette→pausal-plan→confirmation→
clarification→context→intent(+fast/consult)→planner→llm→critic→memory→
learning→dispatch). main.py:run_loop and ui/session._run_turn both DELEGATE
their whole body to it; each front end supplies only a surface adapter
(_TerminalSink in main.py, _UiTurnSink in ui/session.py). No new giant
orchestrator; exposure stayed small and surface-only.

Procedures honored: main.py edits → constitution/lock ownership path
executed (protected.lock regenerated, `verify_lock()` → True, constitution
tests pass again).

Nothing else moved. 415/415 issues clean. 92.3% readiness recomputed.

## 2.0.0 — Architecture completion (MCP + engine + orchestrator + bootstrap)

Migration captures (files): MIGRATION_REPORT.md. Runtime highlights:

- core/bootstrap.py — one startup contract (constitution+config+warmups) used
  by main.py and any host process (protected files re-anchored).
- core/events.py — internal event bus (tool.called/failed, agent started/
  stopped/failed, plan.started/completed/paused, health transitions); the UI
  lifespan mirrors a filtered feed.
- core/workflow_orchestrator.py — owns the specialist-consult route (moved
  from intent/engine.py without changing a single phase contract).
- core/state_manager.py — memory≠state≠context: assembly-only views and one
  cancel_pending() stop gesture.
- agents/engine.py — real lifecycle (discovered→…→stopped) + registry +
  runtime plugin types via register_type (no main.py edits to add specialists).
- mcp/* — policy-gated in-process gateway: file/web/system/knowledge/comm
  adapters; callers (agents) CANNOT reach raw tools — pool lanes go through
  (read-kind only for agents; everything else still via manager+confirmation).
- runtime/service.py — mcp probe + health transitions→events.
- ui/server.py — internal ops feed into the client panel.
Gates: 415/415 pytest · 22/22 second · 45/45 connectivity · 74/74 smoke ·
49/43 arch · readiness recomputed 92.3% READY-WITH-LIMITATIONS.

## 1.9.0 — Repair mission: harder exec, smarter planner, verified health

Mandated findings re-verified (both already fixed in earlier phases; runtime
evidence attached): agent-pool probe imports the canonical alias
(agents/__init__) — service probes healthy; ui/tts.py has zero stderr prints.

Repairs this phase (all covered by new tests):
- planner automatic escalation: config.planner_active() with PLANNER_MODE
  (off|auto|on); default auto — complexity-gated planning ON, trivial turns
  still free. Legacy PLANNER_ENABLED contract preserved; main.py + ui/session
  call the new gate; protected.lock re-anchored.
- planner/executor.py: evidence-based completion — a task that succeeds but
  cannot produce its declared expected_result is FAILED (verify-driven).
- tools/exec_tools.py: real containment (PGID kill on timeout, cwd locked to
  project tree, ambient credentials scrubbed from child env, rlimits,
  output caps) — no claim of full OS sandboxing on Termux (documented).
- memory/coordinator.py: one write-routing policy store; learning engine now
  routes through it (persona to JSON, operational to the knowledge DB).
- tools/system_tools.py: +gemini_health (UNVERIFIED without key by design;
  opt-in live round-trip behind ZERION_LIVE_LLM_CHECK=1 / live=true).
- runtime/service.py: resources subsystem (RSS baseline ×3 watch + rcfg cap)
  and the agent pool reaper wired into maintenance (stale cleanup).
- runtime/rcfg.py: ZERION_MAX_RSS_MB, ZERION_AGENT_REAP_EVERY.
- readiness_audit.py: smoke check parse no longer hard-codes a count.
- tests: +test_exec_hardening, +test_planner_mode, +test_runtime_hardening
  (incl. agent-probe regression + 3000-tick runaway-guard soak proof). 401/401.

Suite: 401/401 pytest · audits green · readiness 92.3% READY-WITH-LIMITATIONS.

## 1.8.0 — UI: blue interactive starfield replaces the ball

User request: no ball — a dense field of blue stars, close together, that
interacts with pointer position and moves with Zerion's state and voice.

- modules/orb.js rewritten around a Starfield renderer (same public API:
  initOrb/setState/setAgents/setTools/setAmplitude — zero callers changed):
  3 parallax depth layers, constellation links between near stars via a
  spatial grid, pointer gravity + ice-white proximity highlights, idle drift
  with edge wrap, state-driven motion (thinking=inward swirl, speaking=
  center waves driven by live voice amplitude, analyzing/searching=scan
  band, success=blue spark burst, error=fast jitter), all on a #000 field.
- workspace.css: orb-stage is black by default (canvas-edge flashes safe).
- smoke: +2 auto-fullscreen checks (1.7.0) + starfield API probe → 74/74.

Gates: 379/379 pytest · 22/22 second audit · 45/45 connectivity · 74/74
UI smoke · ZIP extract-validated.

## 1.7.0 — Offline-key UX + UI boot surface + phone fullscreen defaults

User-reported: "still offline and ui still bad and not auto full". All three
traced to real defects and fixed with tests:

- config.py: python-dotenv load was CWD-only → launching Zerion from outside
  the project folder silently dropped .env (the classic "Zerion is offline"
  despite a valid key). Now anchored to the project root with cwd override
  preserved. test: anchored load from any cwd.
- llm.py: missing-key errors now answer with the fix ("add GEMINI_API_KEY to
  .env or run python setup.py") instead of a bare provider traceback; both the
  integration test and second_audit contract updated to the guided text.
- setup.py: interactive key prompt on real terminals (TTY only; never echoes,
  never logs; writes .env and re-verifies config on the spot).
- ui/static/index.html + main.js: boot watchdog + fatal-error panel —
  a blank/blocked page now reports WHY (module load failure, WS unreachable)
  and how to repair it, instead of dying white. Plain-JS inline (safe even
  when the module graph fails to parse) and quieted once boot completes.
- store.js: autoFullscreen now defaults ON for phone-class viewports
  (small screen or coarse pointer), OFF for desktop — browser gesture rules
  remain (first tap enters immersive mode; no silent force); smoke-proven
  both directions.
- README/audits: contract migration documented (keyless message text).

Suite: 379/379 pytest · 22/22 second audit · 45/45 connectivity · 72/72 UI
smoke · ZIP extract-validated.

## 1.6.0 — Brain verification & cognitive-integrity repairs

Found by tracing the real runtime path (not by reading architecture docs):

- planner/decomposer.py validated tool names against the TOKEN-TRIMMED
  relevance subset — planner-chosen tools like `calculate` were silently
  downgraded to reasoning-only steps. Fixed: tools are validated against
  the real tool registry (context stays a prompt economy, never authority).
- intent/fast_planner.py: failed direct tools now surface `tool_success`
  and parameterized failures fall through to the LLM repair path rather
  than answering with raw error text.
- intent/engine.py: action history now records true success/failure for
  fast-path tools, and failures seed error memory (future avoidance).
- core/turn_pipeline.py: brain-state vocabulary + mapping
  (BRAIN_STATES/BRAIN_STATE_MAP) — the state machine documents what the
  UI session already emits per turn (proof in tests, names never invented).
- planner summary regression caught mid-pass (missing final return after
  the vocabulary edit) — the brain-verification suite caught it the same
  run; this is why the brain suite exists.
- tests/test_voice_service.py: WS receive budgets widened (60→600) to match
  the event bus's real replay volume; product path unchanged (answers in ~8ms).

New evidence artifacts:
- ZERION_BRAIN_MAP.md — full arrow-by-arrow cognitive loop w/ files+tests
- MAIN_BRAIN_GAP_REPORT.md — expected vs actual per component w/ repairs
- tests/test_brain_verification.py — 8 tests: FSM emission, memory→prompt
  influence proof, multi-step planner chain with real tools, executor
  failure anatomy (retry/mark-failed/verifier-skip/sibling-completes),
  fast-tool failure truthfulness + error memory, cross-turn state persistence,
  outbox restart equivalence, offline perf budgets

Performance (sandbox): cold boot 0.165s · import 0.114s · offline turn
27.5ms mean · RSS ≈39MB · 1 idle thread.

Suite: 375/375 pytest · audits green.

## 1.5.0 — Final Integration + Phone Readiness (evidence-gated)

- runtime/selfcheck.py: ZERION SYSTEM CHECK — every row is a real probe
  (constitution lock, memory roundtrip, knowledge DB, 58 tools, agent pool,
  phone binaries, connectors+effective overrides, learning, owner-gated
  evolution staging, models, storage, network reachability, UI import).
  `python -m runtime --check` now prints the matrix + the per-subsystem
  service probe (PASS/DEGRADED/BLOCKED/FAILED/UNAVAILABLE, no green-by-import).
- setup.py: comms/security/intent/knowledge/learning required dirs; import
  sanity extended to comms/engine+autopilot, security/serious_auth,
  learning.controller, intent.multilingual; termux-notification-list /
  termux-contact-list / termux-sms-send probed; Termux permission+background
  guidance printed on phone installs.
- PHONE_SETUP.md: the complete phone installation contract (Android/CPU/RAM/
  Python/Termux versions, packages+binaries, env vars, permission matrix with
  code-gate pointers, one-procedure install, background-mode rules,
  known-not-verified device rows).
- readiness_audit.py: full evidence-weighted scoring pipeline — gates +
  system check + registry identity (agent_pool≡pool) + code probes that prove
  constitutional behaviours (no-flow observe-only, risky parks, ESTOP wins,
  serious requires auth) + gap scan + machine system graph
  (SYSTEM_GRAPH.json: 365 nodes / 1068 edges) + READINESS_REPORT.json +
  FINAL_READINESS_REPORT.md. Current: overall 92.0%, verdict
  READY-WITH-LIMITATIONS (device-gated phone rows UNVERIFIED, never claimed).
- connectivity audit: registration of the readiness audit artifacts + `sh`
  probe documented; .bak runtime artifact classified.

Suite: 367/367 pytest · 22/22 second audit · 45/45 connectivity · 70/70 UI
smoke · arch_map 49/43 · ZIP extract-validated.

## 1.4.0 — Authenticated Serious Mode + Authorized 24/7 Workflows + Constitution v1.1

**Authenticated Serious Mode (§8–§16):**
- semantic multilingual activation — "Turn on serious mode", "فعل الوضع
  الجاد", "شغل الوضع الجاد", spelling/case/Arabic-Latin variants all map to
  ENABLE_SERIOUS_MODE through intent/multilingual.py (stem evidence, never
  exact strings; negation & unrelated 'serious' usages stay inert)
- activation requires local authentication — the installation code
  (nano 808 family, incl. Arabic forms) exists ONLY as KDF constants +
  salted PBKDF2 hash (security/serious_auth.py); never stored plaintext,
  logged, remembered, telemetried, or sent to any model
- lockout (3 fails → 300s lock, held even against the correct code),
  count-only security logging, challenge-cancellation words are free
- UI masking: while the challenge is pending, the user's typed code is never
  echoed into the event stream / replay buffer / logs
- strictest-policy interaction: Serious Mode demotes trusted auto-sends to
  confirmations in the comm evidence gate (AUT-002)
- deactivation stays authless ("turn off serious mode", "عطل…")

**Authorized background workflows (§2):** explicit objects (id / platform /
account / scope / allowed actions / risk / expiry — 24h default, hard-stoppable
by command or panel) are now the only path to background replies; without an
ACTIVE scoped flow, autopilot observes and never drafts
(COMM_REQUIRE_FLOW; COMM_FLOW_TTL).

**Constitution v1.1 (§17/§18):** +17 laws — level 6 (background
communication: authorization, scope, isolation, verification, duplicates,
rate limits, untrusted content, sensitive gate, ESTOP, audit, downgrade,
connector isolation), level 7 (serious-mode authentication, security
boundary, credential protection), level 8 (platform limits, safe recovery).
All existing laws unchanged; owner relock + engine verify green; tests map
laws to the actual code gates.

**Wiring:** comms/health.py heartbeat writer (service/listener/queue/
last_event/last_error); runtime probe carries it; UI panel shows serious
badge + bg flows with stop buttons; new control op stop_bg_flow; new tool
comm_flow (trust-forward). 58 tools.

**Contract migrations (mandated, tested):** /serious and 'start serious
mode' now authenticate instead of toggling directly; the regression suite
was updated accordingly.

Suite: 367/367 pytest · 22/22 second audit · 45/45 connectivity · 70/70 UI
smoke · arch_map preserved · ZIP extract-validated.

## 1.3.0 — Background Autonomous Communication (human-safe)

**comms/autopilot.py — the background spine:** every inbound event flows
identity → exactly-once claim → loop guard → classify+store → isolated
conversation state → FIREWALL (injection/exfiltration quarantined before any
drafting decision) → reply-worthiness → separated candidate draft →
consistency + critic lanes → multi-dimensional evidence gate →
AUTONOMOUS (trusted low-risk only) | APPROVAL (parked + notify) | PAUSE
(stop conditions hard-halt). Never a raw LLM→send path.

**New modules:**
- events.py — deterministic event identity + exactly-once processing/action
  registry ('processing' rows survive crashes; recovery revalidates)
- conversation_state.py — strict (platform, account, conversation) scoping;
  wrong-recipient/wrong-account guards are structural
- firewall.py — prompt-injection / exfiltration / sensitive-content / link /
  dangerous-attachment detection (untrusted input is data, never instructions)
- facts.py — candidate grounding vs knowledge-verified states; commitments
  and hard numbers in a draft must be grounded or the draft parks
- consistency.py — contradiction detection within the conversation scope +
  agent-disagreement stop
- decision.py — the evidence gate (intent/context/identity/fact/recipient/
  policy/risk/history/consistency/critic/loop/connector) composing to
  autonomous | approval | pause | observe
- outbox.py — offline-safe queue: TTL expiry, error classification
  (temporary → bounded exponential backoff; auth/permission/unknown →
  STOP+report), revalidation of every re-execution (policy re-evaluated,
  state changes honored)
- loopguard.py — self-echo / bot-marker / cycle-window detection with
  cooldown + audit
- quality.py — telemetry (accept/reject/verify_fail/policy_block/loop…)
  feeding shadow mode and DOWNGRADE-ONLY autonomy gates (no self-upgrade;
  graduation is an owner action by design)
- overrides.py — pause / resume / ESTOP (clears queue) / platform-contact-
  workflow disables; persistent, audited, restart-proof

**Wiring:** runtime service maintenance pump now routes through
autopilot.pump (ingest → outbox drain → worklows); resource-constrained hosts
defer replies while preserving ingestion and all safety gates. New tools:
comm_process (agents/tools can drive the pipeline), comm_pause, comm_estop,
comm_resume(+confirm), comm_override(+confirm), comm_outbox, comm_autonomy —
56 tools total. UI: Communication panel gains Autonomy & Controls + outbound
queue + quality metrics; new endpoints /api/comm/{autonomy,outbox,control}.

**Config:** AUTOPILOT_ENABLED (default true; sends still need the ladder),
COMM_SHADOW_DEFAULT (new platforms observe-only until the owner graduates
them). DEPENDENCY_MANIFEST updated.

**Proof style:** tests/test_autopilot.py — 32 tests covering the §43
checklist: exactly-once, isolation, injection/exfiltration stops, forbidden
auto paths, high-risk parking, loop cooldowns, offline queue fresh-check,
estop under confirmation, shadow mode, downgrade rules, host-load
deferral, journal integrity (no secrets), and the full low-risk autonomous
send E2E through a faked Telegram transport. Live verification over HTTP for
autonomy/outbox/control endpoints.

Suite: 338/338 pytest · 22/22 second audit · 45/45 connectivity · 70/70 UI
smoke · arch_map preserved · ZIP extract-validated.

## 1.2.0 — Universal Communication & Action Layer

**comms/ package (16 modules) — the intelligent action layer:**
- models: UnifiedMessage + Draft contracts (platform normalization, stable
  dedupe ids, permission facts carried per message)
- connectors: Email (imaplib/smtplib, env-only credentials), Telegram
  Bot API (urllib, env-only token), Phone inbox (termux-notification-list
  → social/phone notifications). Connectors register only when actually
  configured; health states are honest (disconnected/error/degraded/
  connected/authenticated); one broken connector never affects the others
- inbox: unified store (comm_* tables on the existing SQLite file),
  classify (urgent/work/financial/social/system/spam/low), urgency, views:
  search/filter/prioritize/group-by-person/group-by-task/summarize
- reply engine: context = conversation history + contact context +
  knowledge retrieval + user preferences; tone from classification;
  online drafting via the existing provider chain, offline template
  explicitly marked generated_locally (never impersonates model output)
- approvals: 4-level ladder (observe/draft/confirm/trusted) with one-way
  escalation — risk markers (financial/credentials/legal/sensitive/
  irreversible/mass) force confirmation even on trusted rules; scopes
  revocable per platform/account
- anti-spam rails: platform rate window, recipient cooldown, recipient cap,
  duplicate content detection — fail-closed on ledger errors
- engine: the ONLY send path — policy → pre-send checklist → rails →
  connector → platform-result verification → audit + ledger + learning
- workflow engine: data-defined workflows (trigger/conditions/steps),
  adaptive on_fail alternatives, step outcomes observed between steps;
  learning integration stores workflow PATTERNS (never message bodies)
  and routes failures into error memory
- scheduler: trigger pump on the 24/7 service maintenance cadence
  (bounded, no-op without connectors, degrades in logs not crashes)
- calendar: local authorized calendar — create/list/update/cancel, conflict
  detection, availability math, due reminders, meeting-request suggestions
- contacts: minimal purpose-bound contact intelligence (book + guarded
  termux contact list); sync from inbox keeps senders only, never content
- audit: append-only JSONL trail; credential-pattern keys auto-redacted;
  secrets (EMAIL_PASSWORD, tokens) are never logged anywhere

**Security invariants kept:** comm_send/calendar_add/workflow_run are
destructive tools → the existing Constitution policy check + human
confirmation flow applies byte-identically. Agent 'communicator' type can
read and draft but its whitelist excludes comm_send — only humans approve
sends. No bypass exists.

**Tools:** +9 → 50 total (comm_inbox, comm_draft, comm_send, comm_health,
contact_lookup, calendar_list, calendar_add, workflow_list, workflow_run).

**UI:** Communication panel (connectors, unified inbox, pending drafts with
approve&send, workflows + recent runs, audit tail); 6 new /api/comm/*
endpoints, all consumed by the panel; nothing faked — empty connectors show
honest empty states.

**24/7:** new 'comm' health subsystem reports connector errors; maintenance
loop polls triggers.

**Tests:** tests/test_communication_layer.py — 53 tests incl. the four
mission-mandated E2E chains (email / telegram / phone-social / workflow)
over injected fake transports, approval ladder, anti-spam rails, audit
redaction, calendar math, connector honesty.

Bugs found while wiring (all fixed, all proven by tests): calendar free-slot
math used busy-end instead of busy-start; short risk markers now match on
word boundaries ('nda' no longer fires inside 'calendar'); telegram
normalize handled absent bot profile; reply targets are platform-correct
(bare email addresses, telegram chat ids).

Suite: 306/306 pytest, 22/22 second audit, 45/45 connectivity, 70/70 UI
smoke, arch_map preserved.

## 1.1.0 — Reality-Map Integration (agents + learning wired into runtime)

**P0 defect repairs (verified in REALITY_MAP.md, now fixed and re-verified):**
- runtime/service.py agents health probe imported a nonexistent symbol
  (`agents.service.agent_pool`) — every health tick degraded the subsystem.
  Fixed to the canonical public surface; probe verifies `agents: healthy`.
- ui/tts.py: four raw stderr debug prints removed; structured core.logging
  debug channel used instead. Test asserts silence.

**Agent runtime integration (agents were REGISTERED_NOT_EXECUTED):**
- intent/engine.py consults the canonical Agent Orchestrator after the fast
  planner for multi-domain CHAT requests — zero extra LLM cost, gated by
  config.ORCHESTRATION_ENABLED (env + UI runtime setting).
- Evidence discipline: whitelisted knowledge/long_term layers, ≥50%
  on-topic token coverage, critic-accept required for direct answers;
  "revise" verdicts inject explicitly-uncertain context instead. Self-echo
  (capability-gap/critique/knowledge_gap records quoting the request)
  provably cannot answer a request.
- agents/orchestrator.py: lanes fan out in parallel under one shared 20s
  deadline; one bounded restart on transient failure; every lane returns
  the structured result contract (task id, evidence, confidence, tools,
  duration, verification status).

**Learning controller activation (was tool-only):**
- learning/triggers.py: explicit "learn <topic>"/"teach yourself …"
  trigger executes the canonical loop offline; repeated same-tool failures
  (≥3/session) surface a structured signal — never silent auto-learning.
- /learn <topic> palette command → same learn_domain path as the LLM tool.
- BackgroundLearning.run_once reports spaced-recall dues at idle.
- Error memory keyed by concept; wide-window retrieval so ranked noise
  can't hide failures; critic flags weak summaries at store time
  (critic-flagged tag, reduced confidence — never silent promotion).
- Curriculum prerequisite_of / part_of edges written to the existing
  intelligence/world graph and consulted when a practice attempt fails.

**Bugs found by the new end-to-end test (both fixed):**
- learning/errors.py crashed when failure payloads were ints — the
  learn-from-failure path was effectively unreachable.
- learning/controller.py generalization probes reused identical seeds for
  runs inside one second — "unseen" probes could repeat verbatim. Now
  salted with run_id.

Suite: 253/253 pytest (233 baseline + 20 integration tests), 22/22 second
audit, 45/45 connectivity, 70/70 UI smoke, arch_map 49/43 preserved.

## 1.0.0 — Universal Learning (evidence-driven loops, never fake)

- learning/acquisition.py: classify every learn fragment as
  source/claim/fact/interpretation/hypothesis/unknown; unknown markers win
  precedence over fact markers, so nothing is treated as truth by default.
- learning/verification.py: truth states VERIFY/SUPPORTED/UNCERTAIN/
  CONTRADICTED/REJECTED; multi-source aggregation and executable tests override.
  Never fabricates.
- learning/curriculum.py: dynamic curriculum with prerequisite ordering and
  adaptive re-order based on measured performance (never a static script).
- learning/practice.py: progressive difficulty exercises with measurable
  verdicts (not voice… actual attempts measured).
- learning/errors.py: structured error memory (problem→attempt→cause→fix
  →solution) through the canonical knowledge store.
- learning/progress.py: multi-dimensional learning progress (mastery/
  verify-rate/generalization/error count — never one arbitrary percentage).
- learning/retention.py: adaptive spaced recall (double on pass, halve on
  fail, bounded 1..90 days) driving "what's due".
- learning/transfer.py + learning/meta.py: domain transfer of general
  principles and measured learning-strategy comparison.
- learning/controller.py: the LearningController implements the full loop:
  ASSESS → GAPS → CURRICULUM → ACQUIRE → PRACTICE/EXPERIMENT → FEEDBACK →
  VERIFY → GENERALIZE → STORE → REVIEW → MEASURE. Calls out when stuck
  instead of guessing.
- tools/learning_tools.py: learn_domain / learn_progress / review_due via
  the Tool Manager contract (nothing bypasses policy).
- runtime/service.py: learning subsystem's health probe now reports review
  backlogs so retention debt is visible, not hidden.
- tests/test_learning_system.py + tests/demo_self_teaching.py: the mandated
  synthetic-domain experiment is fully measured (mistake→correction→
  generalization) — never a narrative-only demonstration.

## 1.0.0 — world-class intelligence integration
- cognition/decisions.py: structured option-stacking (options/cost/risk/
  benefit/uncertainty/reversibility/evidence → decision with bounded
  confidence); decision tasks ride the reasoning-mode channel as
  "decision_analysis" so every terminal+UI turn gets honest consequences.
- cognition/context.py: relevance-ordered, budget-bounded prompt assembly;
  llm.py now goes through it, so EVERY entry point benefits without a second
  prompt engine. Long contexts get hierarchical head+tail compression.
- providers/gemini.py + plain kwargs multimodal chain: image_b64 flows
  through the single Gemini provider as an inline part; older 2-arg fakes
  and providers stay compatible (kwargs only when an image exists).
- ui vision turn: image bytes → same brain (same critic, same memory).
- meta.py: honest self-knowledge answers (memory stats, tools count, agent
  types, device state) — zero-cost via fast_planner.
- benchmarks.py: REAL measured lenses (reasoning, decision, tool, memory,
  orchestration, offline-intent, constitution), appended to runtime/run/
  benchmarks.jsonl for the evolution self-competition loop.
- fixes found while extending: meta-prompt markers no longer swallow recall,
  legacy 2-arg provider contract guarded, vision tail restored intact.

## 1.0.0 — the canonical Agent Orchestrator
- agents/orchestrator.py: minimal-capable offline classification → type
  selection → bounded pool lanes → aggregate → self-critic review →
  verification marker → telemetry record → release. AgentMessage schema in
  agents/messages.py implements the required fields. Full lifecycle states
  (registered→selected→initialized→executing→verified→completed→released)
  recorded on every agent.
- agents/types.py extended by the true specialist gaps: architect, tester,
  security, data, finance; mandated five behavioral types retained. All
  whitelists remain read-only — output never bypasses the confirmation path.
- tools/test_tools.py: bounded run_pytest (rlimits reuse, 120s ceiling,
  project-relative paths only); orchestrator_tools.py: agent_orchestrate +
  agent_performance through the Tool Manager contract.
- runtime/service.py: 'agents' HealthMonitor subsystem probe (backlog +
  failure-posture); ui/session.py: orchestrator roster row on agent runs.
- Telemetry-informed improvement: orchestration outcomes stored as KB
  capability records (layer='capability') so future selection is learned,
  not hardcoded.
- Verified: 209/209 backend tests · 70/70 UI smoke · 45/45 connectivity ·
  22/22 second audit · orchestration reaches the real main.py loop message
  chain (test_final_e2e).

## 1.0.0 — single-screen AI-OS UI deepening
- Core orb: full mandated state vocabulary (ready/thinking/analyzing/
  executing/listening/speaking/searching/coding/learning/self-upgrading/
  warning/offline/focus-mode/error/success). Orbital tool markers while a
  tool executes; linked stream halos while agents work; offline dims the
  Core instead of only showing a banner.
- Focus Mode is real now: floating bar with the live task, completed/total
  steps, and a STOP button that calls the Core's cancel path (no fake pause).
- Phone workspace mode auto-surfaces on body activity and settles back to
  conversation when finished (no manual switching).
- Genuine data: storage telemetry landed in System Status; GPU intentionally
  absent unless detected; session emits analyzing/executing/warning correctly.
- 70 UI smoke checks, 198 backend tests, 45 connectivity checks all green.

## 1.0.0 — phone becomes first-class physical body
- New phone body layer: phone/state.py (live PhoneState with TTL refresh;
  honest None where unprobed; permission posture; current-action tracking;
  last-verification tracking), phone/actions.py (structured PhoneAction with
  full lifecycle: action_id, risk, approval, execution, verification), and
  phone/manager.py (PhoneBodyManager orchestrator: capability validation →
  constitution gate → approval gate → existing PhoneDispatcher execution →
  failure classification and bounded retry → honest verification → state
  refresh + append-only audit at runtime/run/phone_audit.jsonl).
- Verification is honest: verified_success requires platform readback; when
  the platform offers none, the result is reported as execution_unverified
  and the message says so. Failure is never faked.
- Existing phone modules extended additively, never duplicated: controllers
  gained volume/vibrate/state-read tools; dispatcher call table extended
  (volume, vibrate, battery_state, wifi, media); extractor vocabulary grew
  (battery, wifi, vibrate, volume %, music play/pause/resume); engine composes
  the body (phone.engine.PhoneIntelligence.body). ui/session drives the body
  so Web UI conversations go through the complete lifecycle; main.py terminal
  path (hash-locked) keeps the same dispatcher + approval behavior.
- UI surface: /api/phone/state (read-only snapshot incl. pending approvals
  and recent actions), phone_state WS events on every action, System-Status
  body fact row in the left rail.
- 9 new tests (test_phone_body.py) prove: approval parking, constitution
  non-bypass, missing capabilities denying cleanly, transient-only retry,
  audit trail, and all five self-aware state queries.
- Full suite: 198 passed.

## 1.0.0 — emergency repair pass (voice service + pipeline unification)
- FIX THE GEMINI TTS GAP: Web UI voice now goes through ONE authoritative
  path — the Core's own speech.py Gemini TTS — served as expiring
  /api/tts/<token> URLs. ui/tts.py service: content-hash dedupe, rate
  limit, TTL tokens, threadpool off the event loop, zero key exposure, no
  client-supplied paths. Voice-state chip shows GEMINI VOICE / VOICE… /
  BROWSER VOICE (explicitly-labeled fallback) / VOICE OFF / VOICE ERROR.
- TURN PIPELINE UNIFICATION: new core/turn_pipeline.py owns shared turn
  semantics (confirmation vocabulary, interrupt words, canonical plan
  summary prose) — consumed by BOTH main.py and ui/session.py. Also
  unified the duplicated JSON-extraction helper (planner now imports
  llm.safe_json_parse).
- Agents are now unbounded by fixed counts: instances queue; execution
  concurrency is derived from host resources (cores/RAM) with a
  resource-informed backlog limit. stats() exposes capacity + resources.
- Audit system now parses the custom @route() registry + knows
  WS/token-URL routes; vocabulary: REACHABLE / DYNAMICALLY REACHABLE /
  LEGACY / INTENTIONALLY UNUSED / DEAD / UNKNOWN.
- New evidence tests: cognition-influence proofs (memory/knowledge/
  reasoning/confidence/tool-results provably reach the prompt), Gemini
  edge battery (5xx, Retry-After, empty/malformed), voice-service unit +
  LIVE-WS integration battery, agent resource scaling.
- Bugs found and fixed by this pass: MAX_TEXT instance-attribute crash,
  WS single-writer race (per-connection send lock), welcome overlay
  duplication on re-hello, cross-test knowledge-DB pollution.
- Suite: 189+ backend tests · 66 UI smoke checks · second audit 22/22 ·
  connectivity audit 30/30.

## 1.0.0 — entry-point consolidation
- main.py is now the single official door and boots the Web UI by default:
  `python main.py [--host --port]`. A minimal built-in REPL remains via
  `--terminal` for UI-less hosts; missing UI extras degrade to it with a
  clear install hint. terminal.py retired (its surface is absorbed).
- main.py UI path wires SIGTERM→graceful shutdown (uvicorn only handles
  SIGINT itself) and best-effort browser auto-open.
- protected.lock re-locked after the owner-directed main.py change
  (constitution integrity chain intact — verify_lock passes).
- tests/test_entrypoint.py proves: default = UI serving, --terminal REPL,
  --help, graceful shutdown both signals, no duplicated pipeline internals.
- setup.py/docs updated to the new entry contract.

## 1.0.0 — Final release candidate built & verified
- Phone body: phone/device.py host probe (platform/arch/screen/RAM/storage/
  battery/network/sensors, Termux-rich, desktop psutil//proc fallback) +
  tools/device_state_tool.py — the Core knows what it runs on.
- Agents: new agents/ package — five fixed types (researcher/coder/
  verifier/controller/monitor), dynamically instantiated instances,
  resource-bounded pool (capacity from cores+RAM, per-type caps), whitelist
  enforcement (nothing destructive without the supervised path), delegation,
  aggregation, restart budget, reaping; exposed via tools/agent_tools.py.
- Skills: 10 additional routable domain packs (mathematics, physics,
  chemistry, health information, legal information, culinary, languages,
  history, mechanical engineering, writing) + skill_route/skill_list tools;
  legacy four-domain routing preserved byte-for-byte behaviorally.
- Smart brain: cognition/reasoning.py emits multi-path hypothesis scaffolds
  for analytic goals (evidence-led/context-gap/environment-led, bounded,
  revisable, evidence-tagged); confidence stays evidence-bounded (.35–.90).
- Personality: personality.py NORMAL/SERIOUS with real prompt-channel effect
  (persona rules ride reasoning_rules into the model context) + natural
  phrase + slash command switching, persisted in long-term memory; safety
  boundaries explicitly remain active.
- Gemini transport verified offline (mocked): auth, request shape, 401/403,
  429 w/ Retry-After, timeout, network failure, malformed replies; TTS
  payload contract (AUDIO modality, prebuilt voice) + PCM→WAV integrity.
- UI: first-run welcome experience (fast, readiness-driven, skippable).
- second_audit.py: release-gate audit tool (19 checks: integrity, imports,
  secrets, runtime behaviors, service lifecycle, full suite, mobile compat).
- Verification: 157 backend tests, 61 UI smoke checks, full second audit
  PASSED. Gemini audio playback + physical Android execution: NOT VERIFIED
  (no audio hardware / no physical device in the build environment) —
  see FINAL_RELEASE.md for the honest verification matrix.

## Unreleased — Core stabilization pass
- Full-core audit (127 modules) + integration verification: new fenced
  guarantees in tests/test_integration_map.py (every module imports; all
  critical pipeline modules stay reachable from main.py; the documented
  dormant set changes only deliberately) and tests/test_main_integration.py
  (real run_loop E2E over a scripted provider: memory persist+recall, fast
  planner, self-critic, tool routing, confirmation gate, planner, idle
  maintenance, clean exit).
- Relocated .env.example to the package root; removed a leftover extraction
  directory; promoted memory/ to a regular package (additive __init__.py).
- Verified signal-driven shutdown and the multi-threaded memory-writer lock.
- No Core behavior changed; main.py and the constitution corpus are untouched
  (hash-locked). Full suite: 109 passed.

## Unreleased — 24/7 runtime + startup greeting (additive layer)
- Added `runtime/` package: long-lived service lifecycle (`python -m runtime`)
  with single-instance flock lockfile, structured JSONL logging with rotation,
  heartbeat + machine-readable status/state files, signal-driven graceful
  shutdown (SIGTERM/SIGINT, SIGHUP reload), resource cleanup hooks, and
  run-state persistence that reports unclean previous runs.
- Added HealthMonitor: per-subsystem probes with HEALTHY/DEGRADED/RECOVERING/
  FAILED/DISABLED states, recovery with immediate verification, per-subsystem
  exponential backoff, restart budget (runaway protection), critical-only
  escalation to clean shutdown, and slow re-probing of FAILED optional
  subsystems so external healing is detected. Monitors: core integrity,
  API/UI host, memory, knowledge, learning, phone, voice, model, workers.
- Added startup greeting: fires once after READY (never during init), voice
  via the existing speech module with text fallback, configurable via
  ZERION_GREETING / ZERION_GREETING_ENABLED, uses the stored profile name only.
- Added explicit opt-in autostart generation (systemd user unit, Termux:Boot
  script); nothing is written without `--yes`.
- The standalone UI server startup now delivers the same READY greeting.
- Added `tests/test_runtime.py` (34 tests). Full suite: 98 passed.

## Unreleased — WebUI (additive layer)
- Added the official Zerion WebUI (`ui/`): an adaptive "AI Operating System"
  workspace — one screen that reshapes itself from Core classification events
  (chat / coding / research / trading / vision / automation workspaces, focus
  mode, live Core orb with per-state animation, system telemetry, agents
  roster, goals/tasks/decisions feeds, terminal through the Core tool policy,
  floating explorer/logs/memory/developer panels, settings incl. runtime Core
  toggles, multi-device smart layout, gestures, monitor pop-out view).
- The UI is a front-end adapter (`ui/session.py` mirrors `main.py`'s turn
  pipeline branch-for-branch; session state imported from `main.py`). No Core
  behavior changed; all state-changing UI actions route through the existing
  engines and the Tool Manager's confirmation flow.
- Added `tests/test_ui_bridge.py` (14 tests) and a headless client smoke test
  (`ui/smoke/smoke.mjs`, 58 checks). Full Core suite remains green.

## 1.0.0-rc.1 — 2026-08-05
- Added Constitution integrity and protected-core checks.
- Added staged evolution protection, backup, versioning and rollback.
- Added knowledge, experience, reflection, capability and runtime intelligence records.
- Added provider dispatch adapter and persistent local health store.
- Added supervised phone parameter extraction and dispatch contract.
- Added optional offline voice adapter for Piper or Termux TTS.
- Hardened execution: removed `shell=True`; added bounded isolated Python execution.
- Added regression tests for Constitution, memory, execution, provider dispatch, voice, phone, capability and intelligence paths.
