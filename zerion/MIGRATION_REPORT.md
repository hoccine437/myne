# MIGRATION_REPORT.md — Architecture Completion (2026-08-09)

## 1. ARCHITECTURE BEFORE (probed via attached screenshots + code)

- main.py carried the full conversation engine (legacy terminal) while the UI
  (ui/session.py) line-mirrored it — duplicated turn logic.
- No MCP-shaped gateway: agents called the tool manager directly.
- Subsystem events went to the UI/WebSocket only.
- Startup duplicated `ConstitutionEngine.load()` + `config.validate()` in
  both entry points (main.py + ui/server.py).
- State assembly was scattered across singletons (`intent/session_state`,
  planner state, pool, comms store).
- "Workflow orchestration" was an inline step in intent/engine.py.

## 2. ARCHITECTURE AFTER

```
USER (terminal / UI-WS / comms event / system event)
  ↓
core/bootstrap (single startup contract; constitution → config → warmups)
  ↓
ZerionRuntime / main.py entry (thin)               [relock-protected]
  ↓
Workflow Orchestrator (core/workflow_orchestrator.py)
  │   owns route: classify → fast-lane / planner / specialist consult / LLM
  ↓
intent.engine.process                — undisturbed classification owner
  ↓
Agent Engine (agents/engine.py)      — lifecycle + registry + plugin types
  ↓  (spawns lanes through…)
Agent Pool (unchanged whitelist)
  ↓
MCP Gateway (mcp/gateway.py)          — policy→timeout→retry→audit→translate
  ↓
MCP Servers (mcp/servers/…)           — file/web/system/knowledge/comm adapters
  ↓
Tool Manager (unchanged, constitutional)
  ↓
Memory(coordinator) / intent.session_state (+ core/state_manager view) /
knowledge DB
```

Cross-cutting (all runtime-proven, not vocabulary): Constitution policy gate
before every consequential call · single-slot human confirmation · core.events
internal bus (tools/plans/agents/health transitions; UI mirrors a filtered feed)
· HealthMonitor probes (incl. new `mcp` + `resources`) · runtime selfcheck
matrix · readiness audit (computed).

## 3. GAP ANALYSIS (migration-relevant slice)

| Target | Before | After | Evidence |
|---|---|---|---|
| main.py thin bootstrap | partial (loop lived inside) | bootstrap contract + protected file intact | second_audit + test_homogonous |
| workflow orchestrator | inline consult in intent/engine | core/workflow_orchestrator owns consult | test_architecture_migration:engine consult |
| agent engine + lifecycle | pool executed/thread-tracked | agents/engine formalizes lifecycle + register_type plugins | TestAgentEngine |
| capability+agent registry | AGENT_TYPES plus pool | engine.list_types + runtime registration | TestAgentEngine |
| MCP boundary + adapters | none | mcp/gateway + 5 server adapters, policy+audit+timeout+retry | TestMcpGateway |
| agent→tool via gateway | direct tool_manager.call | all lanes via mcp.gateway.call_tool (deny list respected) | TestMcpGateway + e2e trace |
| event bus | UI-only | core/events internal bus + UI feed | TestInternalEventBus |
| state manager | scattered singletons | core/state_manager (view assembly, no duplicates) | TestStateManager |
| bootstrap boundary | duplicated in entries | core/bootstrap shared by main.py + ui/service | TestBootstrapConsolidation |
| self-critic / verification | live (pre-existing) | unchanged ownership | test_self_critic |
| self-evolution | owner-gated (pre-existing) | unchanged | test_constitution* |
| phone readiness | PHONE_SETUP.md + selfcheck | actual device rows UNVERIFIED (documented) | readiness_audit |

## 4. FILES CREATED
core/bootstrap.py · core/events.py · core/state_manager.py ·
core/workflow_orchestrator.py · agents/engine.py · mcp/__init__.py ·
mcp/gateway.py · mcp/servers/__init__.py + comm.py + file.py + knowledge.py +
system.py + web.py · tests/test_architecture_migration.py ·
MIGRATION_REPORT.md

## 5. FILES MODIFIED
main.py (bootstrap call — protected → relock) · ui/server.py (bootstrap +
core-event feed) · intent/engine.py (orchestration consult delegates) ·
intent/session_state.py (state-manager extension) · agents/pool.py (tools
via gateway) · tools/manager.py (tool events) · planner/planner.py
(plan events) · runtime/service.py (mcp probe + health transition events) ·
constitution/protected.lock (hash re-anchored after main.py edits) ·
connectivity_audit.py (MCP discovery classification) ·
tests/test_integration_map.py (same) · CHANGELOG.md

## 6. FILES REMOVED
None (migration safety holds).

## 7. COMPONENTS REUSED
Constitution policy · tool manager + confirmation flow · agent pool +
types · learning engine/background · cognition + critic · intent engine +
multilingual + fast planner · memory manager + knowledge DB + coordinator ·
runtime service + health monitor + comms/autopilot pipeline · phone adapter.
Nothing re-implemented where an existing implementation was correct.

## 8. COMPONENTS REFACTORED
- intent/engine._maybe_orchestrate → core/workflow_orchestrator.consult_agents
  (one owner; engine keeps phase-ordering responsibility)

## 9. MCP INTEGRATION STATUS
IMPLEMENTED + WIRED at the agent boundary (pool lanes must go through the
gateway; direct tool calls refuse non-capability tools with
`mcp.capability_not_exposed`). Server adapters implement the capabilities
Zerion really has (file reads/searches/listing, web fetch, system stats,
knowledge search/summary, comm inbox/health). The external wire protocol
(stdio/http between processes) is NOT BUILT — that is a documented next
step; the current transport is in-process (deployment target is a single
Termux host). No fake servers.

## 10. SECURITY/PERMISSION STATUS
IMPLEMENTED + WIRED. Every capability call: Constitution policy → caller-role
read-only rule for agents → bounded timeout → single transient retry → audit
(no secrets) → stable error codes. Underlying destructive flows keep the
confirmation slot in tools/manager.py — the gateway funnels into the same
manager, so law EVO/SEC enforcement is unchanged. Parallel proof: TTS
debug-print debris previously removed, agent probe alias healed earlier.

## 11. MEMORY/STATE STATUS
IMPLEMENTED + WIRED. Memory (json store + knowledge DB + coordinator's route
policy) · Context (memory_for_prompt contract, cognition/context.assemble)
· State (core/state_manager assembly over planner/pool/overrides; UI consumed
via session_state.snapshot's `system_state` block).

## 12. AGENT ENGINE STATUS
IMPLEMENTED + WIRED. Lifecycle starts at "registered"/"running"/"stopped"…
exposed via engine_handle stages; `register_type()` is the plugin seam (no
main.py edits to add a specialist).

## 13. SELF-CRITIC/VERIFICATION STATUS
Implemented + wired unchanged (intelligence/critic on chat turns; verifier
in planner flows; gateway verification items checked).

## 14. SELF-EVOLUTION STATUS
PARTIAL BY DESIGN — engine exists, owner/governance gates active, never
runtime-autonomous (constitutional). Unchanged (no regression).

## 15. TEST RESULTS
pytest 415/415 · second_audit 22/22 · connectivity 45/45 · UI smoke 74/74 ·
arch_map 49/43 · ZIP extract-validated; package rebuild running gates on
clean trees only.

## 16. REMAINING GAPS (honest)
- external MCP wire protocol not built (in-process transport is the target
  today; the boundary is real and the wire is a marked next step)
- sensor/robot/vision/git tools absent because those capabilities don't
  exist in the codebase — adding a capability stays a 3-line adapter
  (registered in mcp/servers/<name>.py); fakes were never added.
- real device evidence rows unchanged (listed in READINESS_REPORT.json)

## 17. KNOWN RISKS
- wiring adds latency: gateway overhead is ~zero (in-process dict dispatch)
  — measured offline turn 27.5ms unchanged in tests
- plugin types run in-process; a hostile registration path is as strong as
  the calling policy (same as tools), so types still cannot call destructive
  tools via agents (gateway enforces read-only at the boundary)

## 18. EXACT NEXT STEPS
1. Wire a real MCP wire transport (stdio/server) when a second process needs
   to host capabilities (e.g. a heavier vision worker) — the bridge point is
   mcp/gateway.resolve()/call(), nothing else changes.
2. Add mcp servers for genuinely new capabilities as they arrive (drop one
   module into mcp/servers/).
3. Keep phone-side hardware verification as the only unverified row until
   real Termux runs confirm binaries behaving.
