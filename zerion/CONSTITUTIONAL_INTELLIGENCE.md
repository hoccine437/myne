# Constitutional Intelligence Layer

## Architectural evolution
Phase 6 is additive. Existing intent, planning, tools, memory, learning, skills, and Phase 5 deployment stay intact. `CognitiveEngine` is inserted before existing intent/planning context construction. It starts from the user's goal, creates a task-scoped reasoning mode, identifies a possible knowledge gap, and supplies context to the existing engines.

## Cognitive freedom / external governance
The Constitution permits reasoning, retrieval, reflection, learning, research proposals, and capability proposals. It requires user approval for deploy/modify/delete/shell/Python execution. Protected components are rejected with an additive alternative. The policy does not execute anything.

## Dynamic modes
`cognition.modes.select_mode()` creates immutable short-lived data for programming, research, planning, security analysis, or general reasoning. It is discarded after the turn. Existing skills remain compatibility metadata only; they do not determine task control flow.

## Curiosity and capability evolution
`CuriosityEngine` detects low-evidence goals and stores a ranked `knowledge_gap` record. It never performs network research or changes code independently. `CognitiveEngine.propose_capability()` produces a proposal; Phase 5 is still the sole path for review, testing, approval, versioning, deployment, and rollback.

## Verification
`tests/test_constitutional.py` validates protected-file enforcement, approval requirements, temporary mode selection, gap recording, and proposal-only capability evolution.
