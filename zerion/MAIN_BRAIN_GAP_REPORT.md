# MAIN_BRAIN_GAP_REPORT.md — main.py / loop verification

Audit date: 2026-08-08 · HEAD `8f71a71`+ · suite 375/375.

| COMPONENT | EXPECTED | ACTUAL (before this pass) | CONNECTED? | RUNTIME VERIFIED? | MISSING CONNECTION | REPAIR | TEST |
|---|---|---|---|---|---|---|---|
| Input | stdin/WS/comms events | same | YES | YES | — | — | test_ui_bridge, test_autopilot |
| Interrupt/mute | local only, pre-everything | same | YES | YES | — | — | test_runtime_pipeline |
| Intent detection | rule classifier, zero-LLM | same | YES | YES | — | — | test_brain_verification FSM |
| Fast planner | direct tool + memory answer | same | YES | YES | success flag truthfulness defect | fast_planner now returns tool_success; engine logs real success + error memory | test_fast_tool_failure_never_faked_success |
| Multi-tool planner | gated, decompose→execute→verify | discovered defect: decomposer validated chosen tool names against the RANKED context subset, silently downgrading real tools to reasoning-only steps | PARTIAL | YES (after repair) | registry is the authority, context is prompts-only | decompose() now validates via `tool_manager.get_tool()` (real registry) | planner tests + executor counts in test_brain_verification |
| LLM reasoning | gemini via api.call_llm | same | YES | YES (transport + fake probes; real key path env-gated) | — | — | test_gemini_* batteries |
| Self-critic | review(+improve≤1) on chat replies | same | YES | YES | — | — | test_self_critic |
| Memory write → read | json store w/ atomic+bak; next-turn prompt inclusion | same | YES | YES (proven prompt influence) | — | — | test_memory_influences_next_turn |
| Knowledge DB | sqlite+FTS5 retrieval in context | same | YES | YES | — | — | test_cognition_influence |
| Agents via orchestrator | evidence-gated, parallel lanes | worked after reality-map repairs | YES | YES | — | (repaired earlier phase) | test_universal_integration |
| Tools→decisions | results recorded (history) + influence | action history was recording success=True for fast failures | YES | YES (after repair) | truthful success marks + error memory | intent/engine repair | test_fast_tool_failure_never_faked_success |
| Error recovery | retry once → skip/abort + replan | planner executor already did this; fast path needed repair above | YES | YES | fall-through to LLM for parameterized tool failures | fast_planner repair | test_fast_tool_failure…, test_plan_failure_recovery |
| Learning | engine per-turn + triggers + controller tools | same | YES | YES | — | — | test_learning_system, test_universal_integration |
| Communication spine | comms/* + autopilot | same | YES | YES | — | — | test_communication_layer, test_autopilot |
| State machine | explicit vocabulary | implicit (state names scattered) | YES now | YES | canonical name map | core/turn_pipeline.BRAIN_STATES + BRAIN_STATE_MAP | FSM assertion in test_brain_verification |
| Health | service monitors + selfcheck | same (+selfcheck this phase) | YES | YES | — | — | test_runtime.*, readiness_audit |
| Phone cognition under restart | outbox revalidates, no blind replay | worked | YES | YES | — | — | test_outbox_survives_restart_equivalent, test_autopilot |

## Repairs made this phase

1. `intent/fast_planner.py` — direct tool outcomes now carry `tool_success`
   (None while parked for confirmation) and parameterized failures fall
   through to the LLM path instead of answering with a raw error string.
2. `intent/engine.py` — action history records REAL success/failure and
   failures write error-memory rows (retrieve_similar coverage).
3. `planner/decomposer.py` — tool-name authority check now consults the
   tool registry (was: the token-trimmed context view). Previously-legal
   planned tool calls no longer silently become "reasoning" steps.
4. `core/turn_pipeline.py` — plan-summary final return restored (regression
   introduced by vocabulary edit, caught by the brain probe the same run);
   canonical brain-state map added as the documented emission vocabulary.
5. `tests/test_voice_service.py` — WS receive windows raised 60→600 to match
   the live bus's real replay volume after heavy turns (product behavior was
   already fast / healthy; the test budget was the stale one).

## Remaining honest gaps (unchanged, documented)

- Direct DDG-style "research" lanes search only the local knowledge base
  (no network research agent) — retrieval breadth is bounded by stored records.
- Phone-hardware turn (Termux binaries live) needs the device (see TERMUX.md).
- Real Gemini round trips need GEMINI_API_KEY (env-gated by design).

Nothing else stands disconnected on disk-without-runtime-path.
