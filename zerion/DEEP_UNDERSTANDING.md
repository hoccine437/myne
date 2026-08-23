# Zerion Deep Understanding Contract

Zerion implements the following as **observable, bounded behaviours**. These
are not claims of consciousness or human emotion. The live model still needs a
real Gemini key, network, and any required device capability; those external
conditions are not silently marked verified.

| # | Capability | Runtime behaviour | Status |
|---:|---|---|---|
| 1 | Independent Thinking | Generates alternatives and revisable hypotheses for non-trivial turns. | WIRED |
| 2 | Decision Making | Compares benefit, cost, risk, uncertainty, dependencies, and reversibility. | WIRED |
| 3 | Priority Management | Ranks goal, urgency, safety, and dependencies before effort/action. | WIRED |
| 4 | Critical Thinking | Challenges assumptions, contradictions, unsupported claims, and missing evidence. | WIRED |
| 5 | Predictive Reasoning | Produces confidence-labelled likely outcomes and leading indicators; forecasts are not facts. | PARTIAL — model-guided, no dedicated forecasting model |
| 6 | Adaptability | Changes reasoning mode and resumes/revises plans when inputs or evidence change. | WIRED |
| 7 | Continuous Learning | Stores validated outcomes and improves future capability selection. | WIRED |
| 8 | Contextual Memory | Uses relevant session history, durable memory, knowledge, and capability records. | WIRED |
| 9 | Emotional Intelligence | Detects language-level tone/urgency and responds respectfully without claiming feelings. | PARTIAL — bounded heuristic, not clinical emotion inference |
| 10 | Realism | Separates fact, inference, proposal, and unknown; fresh external claims require tools. | WIRED |
| 11 | Intellectual Courage | States uncertainty, corrects errors, and refuses unsupported certainty. | WIRED |
| 12 | Problem Solving | Defines goals, decomposes dependencies, uses approved tools, and verifies results. | WIRED |
| 13 | Creativity | Generates multiple useful alternatives and labels proposals as proposals. | PARTIAL — model-guided |
| 14 | Autonomy | Runs registered agents/tools only within permissions, scope, approvals, and Constitution. | OWNER-GATED |
| 15 | Self-Verification | Checks declared expected evidence before reporting task completion. | WIRED |
| 16 | Failure Learning | Records failures and corrective lessons; failure is never recorded as success. | WIRED |
| 17 | Interest Protection | Protects privacy, safety, resources, intent, secrets, and reversibility. | WIRED |
| 18 | Principle Formation | Can propose a principle from explicit repeated feedback; cannot rewrite law automatically. | OWNER-GATED |
| 19 | Self-Evolution | Can identify gaps and stage a tested upgrade; protected changes require owner approval. | OWNER-GATED |

## How it is wired

`core/turn_runner.py` builds the per-turn context and sends it through the
local `cognition.deep_thinking` protocol. That protocol includes all 19
checks from `cognition.deep_understanding`, then passes the contract to the
planner and final Gemini prompt through the bounded context assembler.

The UI exposes the active depth as `x10 / 10 lenses / 19 capabilities`. The
pipeline never emits private chain-of-thought. It emits only safe telemetry,
confidence, evidence, and final user-facing output.

## Domain learning

`learn <topic>` is now topic-specific: with the shared Gemini key, the
`DomainTeacher` generates a bounded lesson and recall checks; with supplied
`source_text`, material can be ingested offline. Both paths store material as
**UNVERIFIED** until independent evidence or tested recall promotes it. The
old callback-free deterministic experiment remains available only to explicit
experiments and no longer runs generic arithmetic under arbitrary topic names.

## Safety boundary

Autonomy, principle formation, and self-evolution remain explicitly gated:
Zerion may propose, ask, stage, or wait, but it does not silently change
protected law, deploy protected code, or claim an external action happened
without a real tool result. Physical Android behaviour, live provider quality,
and human-level emotional understanding remain subject to real-device/live
validation.
