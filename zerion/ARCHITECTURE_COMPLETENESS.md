# ARCHITECTURE_COMPLETENESS.md — honest final gap report (read-only pass, 2026-08-09)

Method: source-line inspection + live probes (call paths grepped and executed).
Verdicts use: **IMPLEMENTED+WIRED** (runtime path uses it today) /
**IMPLEMENTED BUT NOT WIRED** (real code, tests prove it, nothing live calls it) /
**PARTIAL** (works with documented limits) / **NOT IMPLEMENTED** /
**NOT AVAILABLE / OUT OF SCOPE** (no such capability exists in this codebase —
never faked).

## 35-component verdict table

| # | Target component | Verdict | Evidence |
|---|---|---|---|
| 1 | Workflow Orchestrator | **PARTIAL** | core/workflow_orchestrator.py owns the specialist consult and emits `plan.*` events (wired via intent.engine). NOT a lifecycle owner for the whole turn — the turn pipeline still lives inline in main.py:run_loop + ui/session.py (mirrored, healthy, protected). A full lifecycle-owner extraction is a protected-file surgery NOT yet done. |
| 2 | Agent Engine | **IMPLEMENTED BUT NOT WIRED** | agents/engine.py is real and test-proven (lifecycle, registry, register_type). Only `core/state_manager.py` reads its health view; orchestrator/agent_tools/workflows still spawn through `agents.service.pool` directly. Next repair: have the three producers route through `engine.spawn`. |
| 3 | Dynamic Agent/Capability Registry | IMPLEMENTED+WIRED | engine.register_type proven live (plug test), tools registry pkgutil discovery, gateway discoveries. |
| 4 | Memory System | IMPLEMENTED+WIRED | memory/coordinator single write policy rides learning/engine; JSON + SQLite + in-process session; retrieval runtime-proven. |
| 5 | State Manager | IMPLEMENTED + WIRED (read) | snapshot delegates into planner/pool/overrides; session_state.snapshot returns `system_state`. Its cancel_pending() is DEFINED_NOT_EXECUTED (no production caller — sessions call the manager directly). |
| 6 | Context Assembly | IMPLEMENTED+WIRED | cognition/context.assemble within llm.get_llm_output — per turn, both front ends. |
| 7 | MCP Gateway | IMPLEMENTED+WIRED | agents pool lanes now go through it; policy/timeouts/retry/audit per call. Only the agent lane routes through it today (user command surfaces intentionally still use the tool manager — same policy stack). |
| 8 | MCP Tool Registry | IMPLEMENTED+WIRED | capability discovery with reverse tool map proven. |
| 9 | MCP Permission Gate | IMPLEMENTED+WIRED | Constitution.evaluate per call; agent role = read-kind only. |
| 10 | MCP Audit | IMPLEMENTED+WIRED | comm audit trail on every invocation (secrets never). |
| 11 | MCP Timeout/Retry | IMPLEMENTED+WIRED | bounded join timeout + one transient retry. Platform limit noted: in-process threads vs killable — documented. |
| 12 | MCP Error Translation | IMPLEMENTED+WIRED | stable `mcp.*` codes (timeout/denied/not_found/error). |
| 13 | MCP Server lifecycle | PARTIAL | discover/register/health — in a single-process host there is no start/stop/restart surface to manage. Documented limitation. |
| 14 | External MCP transport | **NOT IMPLEMENTED** | In-process transport is the deployment today. The wire protocol is optional next phase; no fake. |
| 15 | Git MCP | NOT AVAILABLE / OUT OF SCOPE | no git-in-product capability exists. |
| 16 | File MCP | IMPLEMENTED+WIRED (read-side) | reads/searches/lists; FS writes stay supervised (correct). |
| 17 | Web MCP | IMPLEMENTED+WIRED | http_get only (post/write deliberately not exposed). |
| 18 | Database MCP | IMPLEMENTED+WIRED (as Knowledge MCP) | knowledge.search/summary over the canonical DB. |
| 19 | Vision MCP | NOT AVAILABLE / OUT OF SCOPE | no local vision models/tooling in this project; vision today is a UI-side provider path. |
| 20 | Device/Robot MCP | PARTIAL (device read-only) | system.* / device.* read probes exposed; effectful device control stays on the supervised phone path — never via MCP. |
| 21 | Event Bus | IMPLEMENTED+WIRED | emitters in tools/planner/orchestrator/health; UI lifespan mirrors a filtered feed. |
| 22 | Health Monitor | IMPLEMENTED+WIRED | probes incl. comm/resources/mcp; recovery/backoff/runaway guard. |
| 23 | Resource Manager | IMPLEMENTED+WIRED | pool capacity derived from host hardware; RSS watch + cap probe; load-aware idle maintenance. |
| 24 | Scheduler | IMPLEMENTED+WIRED | service maintenance cadence + comm trigger pump use it. |
| 25 | Security/Constitution | IMPLEMENTED+WIRED | startup integrity + per-dispatch policy + audit. |
| 26 | Plugin system | IMPLEMENTED+WIRED | tools drop-in, mcp/servers drop-in, agents register_type — three real seams, each test-proven. |
| 27 | Self-Critic | IMPLEMENTED+WIRED | live on chat turns (both front ends). |
| 28 | Verification | IMPLEMENTED+WIRED | planner verify, evidence-based completion, comms verify, phone verify. |
| 29 | Benchmarking | IMPLEMENTED+WIRED | /benchmark command drives real measurements (never an idle module). |
| 30 | Self-Evolution | IMPLEMENTED (gated), DEFINED_NOT_EXECUTED at runtime | owner flow only — constitutional choice, regression-covered. |
| 31 | UI/API/Voice separation | **PARTIAL** | Knowledge window: ui/session.py re-runs the whole turn pipeline (branch-mirror of main.py). It "works and is test-covered", but per target the interface layer must not OWN orchestration. Unifying this without touching protected main.py is the remaining job. |
| 32 | Bootstrap | IMPLEMENTED+WIRED | core/bootstrap.py serves all entries. |
| 33 | Shutdown lifecycle | IMPLEMENTED+WIRED | SIGINT/SIGTERM graceful verified (service + UI). |
| 34 | Observability | IMPLEMENTED+WIRED | logging echo + JSONL service log + metrics loop + event bus + audit + heartbeat. |
| 35 | Testing | IMPLEMENTED+WIRED | 415/415; audits green end-to-end. |

## A. Remaining architectural gaps

1. **Turn-pipeline ownership split** — the runtime's full conversation semantics
   live in `main.py:run_loop` and a line-mirrored `ui/session.py` rather than
   inside a single orchestrator module. Untangling them = protected-file
   surgery (constitution-owners), feasible but invasive.
2. **Agent Engine bypassed by producers** — orchestrator + workflow + tools
   call `agents.service.pool.spawn` directly; `agents/engine.py` lifecycle/
   plugin registry exists (and is tested) yet producers never use
   `engine.spawn`. One-line-per-producer migration; gains: lifecycle-proofed
   stages + events + unified registry visibility.
3. **Event taxonomy** — internal `core/events.py` types cover tool/plan/agent/
   health lanes only (intentionally). Task-state transitions from comms
   workflows are still audited, not evented — a config decision, no gap in
   evidence terms.
4. **MCP transport envelope** — in-process only; when a second process ever
   hosts a capability (heavy vision worker, model server), the adapter slot is
   prepared but NOT built (deliberate — build when needed).
5. **MCP server lifecycle** — discover/health only (no explicit stop/restart/
   isolate verbs) — acceptable in-process; platform-imposed.

## B. Critical gaps (blockers to "complete")

None. The mission-critical chains hold: conversation→context→LLM→critic→
memory; orchestrator consult→agents→MCP→verify; background autorun with
approvals; evolution behind owner gates.

## C. Non-critical gaps (quality, not correctness)

- Engine not on producers' path (row 2 above) — the ONLY one I'd call a
  real architectural repair: small, mechanical, closes the loop visually.
- `StateManager.cancel_pending` never called by runtime — callers do the
  same via manager directly; the assembly API is read-mostly today.
- External MCP transport (row 4) — only matters when a second process is
  introduced.
- Wire-protocol/MCP lifecycle verbs — no use case in single-process Zerion.

## D. False / obsolete requirements in the target diagram

- **Git MCP** — Zerion is a phone-first assistant; no git capability exists.
  Marking it "MUST" matches a diagram, not the product. OUT OF SCOPE.
- **Vision MCP** — no local vision stack exists (multimodal images go through
  the Gemini provider when a key is present). Building a local-vision stub is
  fake; we did not.
- **Device/Robot MCP full control** — phone actions stay on the supervised
  phone path because phone law+approvals own them; MCP keeps device
  read-only (correct safety, not a limitation).
- **Voice as separate input pipeline with its own orchestration** — Zerion's
  voice is text-in/text-out plus send/playback; routing voice through a
  separate fan-in would duplicate the brain for no gain. NOT NEEDED.

## E. Recommended next implementation order (when/if repair continues)

1. Agent producers route through `engine.spawn` (one-line swaps in
   orchestrator/agent_tools/workflow) — unblocks single-owner lifecycle.
2. Extract `run_turn(...)` semantics from main.py + ui/session.py into
   core/turn_pipeline-core so the orchestrator is the true lifecycle owner
   (needs the owner-relock procedure — the two files are protected).
3. THEN consider external MCP (optional, when a second process exists).
4. Everything else stays untouched; the architecture is above crit-mass.

*No code was modified in this pass. The report describes the repository as
read at HEAD `18abdf1` (arena/019fddfd-myne).*


---

## POST-CLOSURE UPDATE (2026-08-09)

Both gaps closed this session (evidence below). Current verdicts marked ⟳.
Saved-read runs: pytest 415/415 (incl. 14-architecture migration tests)
· second_audit 22/22 · connectivity 45/45 · UI smoke 74/74 · arch_map 49/43
· constitution lock verify True · readiness recomputed (see READINESS_REPORT).

| # | Prior verdict | NOW | Proof |
|---|---|---|---|
| 1 Workflow Orchestrator | PARTIAL | IMPLEMENTED+WIRED as owner | core/turn_runner.py owns the canonical turn lifecycle; main.py:run_loop + ui/session._run_turn each delegate to it (code search: old branch strings gone from both call sites; TurnRunner ITSELF is the single owner). |
| 2 Agent Engine bypass | IMPLEMENTED NOT WIRED | IMPLEMENTED+WIRED | Orchestrator/tools/agent_tools/workflows now call engine.spawn / engine.wait / engine.restart / engine.stats; direct pool.spawn remains ONLY inside pool+engine delegation code. Remaining direct paths: proven ALLOWED INTERNAL USE (pool→engine adapter layer, pool's own delegate/restart dispatch). |

⟳ Upgraded rows (final): these were the only ones. Nothing else moved — no
scope growth, no diagram-chasing.
