# ZERION_BRAIN_MAP.md — the realized cognitive loop (evidence-verified)

Built from live tracing of `main.py` + `ui/session.py` + the tests in
`tests/test_brain_verification.py`, `tests/test_final_e2e.py`, and
`tests/test_cognition_influence.py`. Every arrow names the actual
file → function and is backed by a runtime proof (tests cited per row).

§17 vocabulary: `core/turn_pipeline.BRAIN_STATES` (canonical states) —
emitted as core_state/stage events by `ui/session.py` each turn
(mapped in `BRAIN_STATE_MAP`); the terminal front end shares the same
pipeline shape in `main.py:run_loop`.

## The loop (primary path = `ui/session.py::_run_turn` ≡ `main.py:run_loop`)

```
INPUT
  terminal input()                                  [main.py: get_input]
  | WS {"type":"message"}                           [ui/server.py: websocket_endpoint → session.process_message]
  | comms event (phone/email/telegram)              [comms/scheduler → autopilot.process_inbound]
  v
PERCEIVING                                          [_run_turn top; event id claimed — comms/events.py]
  v
UNDERSTANDING
  interrupt/mute check                              [core/turn_pipeline.is_interrupt]
  phone-intent extraction                           [phone/extract.py PhoneIntentExtractor]
  command palette + multilingual layer              [intent/commands.py, intent/multilingual.py]
  pending state resolution                          [planner paused / tool confirm / clarification /
                                                     phone approval / serious-auth / flow confirm]
  v
CONTEXTUALIZING + REMEMBERING                       [session "analyzing" state]
  load_memory → minimal_memory_for_prompt           [memory/memory_manager.py load_memory → main.py reducer]
  knowledge.retrieve_context                        [knowledge/manager.py → search.py + FTS5]
  cognition.CognitiveEngine.prepare                 [cognition/engine.py → modes.py (persona rules merge)]
  capabilities.CapabilityEvolution.prepare          [capabilities/evolution.py → reasoning.py]
  reasoning.CognitiveReasoningEngine.reason         [cognition/reasoning.py — strategy/confidence/hypotheses]
  runtime_intelligence.RuntimeIntelligence.prepare  [intelligence/runtime.py — composition/projects/simulation]
  conversation + pending params                     [SessionMemory]
  v
UNDERSTANDING-DECIDE (intent)                       [session stage "intent"/done]
  intent.engine.process = classify                  [intent/classifier.py — zero-LLM rules]
    → fast planner                                  [intent/fast_planner.py — zero-param tools,
                                                     memory lookups, meta-answers (meta.py)]
    → learning triggers                             [learning/triggers.py — 'learn X', failure signals]
    → agent orchestration consult                   [agents/orchestrator.py — 2+ specialist domains,
                                                     evidence-whitelisted, coverage-gated]
    → AI planner (gated PLANNER_ENABLED)            [planner/planner.py: handle_request →
                                                     decomposer → executor (per-task verify) →
                                                     verifier → goals]
  v
REASONING (LLM)                                     [llm.get_llm_output → api.call_llm →
  providers/router.py → providers/gemini.py         bounded assemble() context [cognition/context.py]]
  v
CRITICIZING (chat intents only)                     [intelligence/critic.py: self_critic.review|improve —
  gated by ENABLE_SELF_CRITIC + intent=='chat'      1 review + ≤1 improve per turn, evidence-gated]
  v
MEMORY-WRITING                                      [memory/memory_manager.update_memory (atomic .bak) ]
  v
LEARNING                                            [learning/engine.py: learn_task
                                                     capabilities.learn (stage/confidence telemetry)
                                                     intelligence/runtime.complete (reflection+quality)
                                                     → knowledge DB; phone dispatch journals too]
  v
RESPONDING / ACTING                                 [handle_intent → tools.manager.execute →
                                                     constitution.policy.Constitution.evaluate →
                                                     single-slot confirmation → ToolResult → user]
  v
OBSERVING/VERIFYING                                 [tool results recorded (intent/history); planner
                                                     per-task verifier; post-send verification for comms;
                                                     phone ExecutionVerifier]
  v
IDLE (idle maintenance / health)                    [learning/background.run_once — retention dues;
                                                     runtime/service HealthMonitor; comms autopilot.pump]
```

## Component × evidence rows

| arrow / stage | file | function | runtime proof |
|---|---|---|---|
| input → perception | ui/server.py | websocket_endpoint, session.process_message | test_ui_bridge (WS roundtrips) |
| perception → understanding | ui/session.py `_run_turn` / main.py `run_loop` | command/intent/pending ordering | test_runtime_pipeline |
| understanding → context | llm.py + cognition modules | assemble memory block | test_cognition_influence (prompt-shape proof) |
| context → reasoning | llm.get_llm_output | api.call_llm | test_final_e2e (provider call recorded) |
| reasoning → critic | intelligence/critic.py | review/improve | test_self_critic, test_cognition_influence |
| critic → response | session/_handle chat | bus chat event | test_brain_verification.test_basic_chat_turn_brain_states |
| plan → execute → observe | planner/{planner,decomposer,executor,verifier}.py | handle_request/execute_plan/verify_task | test_brain_verification.multi_step / failure_recovery |
| failure → recover | planner/executor.py | retry-once-then-skip/abort | executor-level test (bad math + good step) |
| act → tool | tools/manager.py | execute | test_execution_safety |
| constitution gate | constitution/policy.py | evaluate (tools.manager.execute line) | test_constitutional + execution_safety |
| orchestration | agents/orchestrator + intent/engine `_maybe_orchestrate` | run/classify | test_universal_integration (accept + fall-through) |
| learning triggers | learning/triggers.py + tools/learning_tools.py | evaluate/learn_domain | test_learning_system |
| learning from outcome | learning/engine.py | learn_task | test_cognition_influence / brain_verification |
| memory write | memory/memory_manager.py | update_memory | brain_verification memory test |
| background events | comms/autopilot.py | process_inbound | test_autopilot |
| health | runtime/{service,health,health probes} + runtime/selfcheck.py | monitor.tick / run_checks | test_runtime.*, readiness_audit |
| state vocabulary | core/turn_pipeline.py | BRAIN_STATES/BRAIN_STATE_MAP | test_brain_verification FSM emission check |

## Performance envelope (sandbox, 2-core/4GB, offline provider fakes)

measured (recorded, not estimated):

- cold start `python main.py --help`: **0.165 s**
- brain module imports: **0.114 s**
- offline turn (context build + intent + LLM stub + critic + learning): **27.5 ms mean / 35.8 ms max**
- RSS after import+turns: **≈ 39 MB**
- idle threads: **1** (nothing spins except uvicorn when running)
- startup ownership note: Terminal boot prints greeting; UI boot greets via
  lifespan hook (once-guarded) — `runtime/greeting.py`

Thermal/battery posture on phone: nothing in idle burns CPU except the
90s idle maintenance tick and (when the 24/7 service runs) 15s health probes
— event-driven wait between duties (no busy loops).


## 2026-08-09 repairs (1.9.0)

- The planner now escalates AUTOMATICALLY on complexity (PLANNER_MODE=auto,
  default): classifier-seen multi-step requests engage the decomposer; trivial
  turns stay free. main.py + ui/session.py call `config.planner_active(...)`.
- Executor: evidence-based completion (expected_result mismatch ⇒ failure).
- exec tools: PGID kill on timeout, cwd locked to project, env scrubbed.
- learning writes route through memory/coordinator.py (single write policy).
- tools: +gemini_health (UNVERIFIED when the key is absent — never faked).

All covered by tests/test_exec_hardening.py, test_planner_mode.py,
test_runtime_hardening.py, test_brain_verification.py.
