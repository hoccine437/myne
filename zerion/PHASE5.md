# Phase 5 — Supervised Evolution System

## 1. Updated architecture
`Intent → Planner → Agent/Tool system → Engineering Engine → Evolution Engine → Testing Engine → Approval-gated Deployment → Memory/LLM`.

This is a plug-in layer: it does **not** modify `main.py`, startup, configuration, prompt, terminal, existing agents, planning, memory, learning, or speech. It is invoked explicitly by a future command/agent integration.

## 2. Evolution architecture
`EvolutionEngine` is a façade over a read-only `CapabilityAnalyzer`, `UpgradePlanner`, `CodeReviewer`, staging-only `UpgradeGenerator`, `TestRunner`, and approval-gated `DeploymentEngine`. SQLite/LLM/network/package installation are not required.

## 3. Engineering workflow
`EngineeringArchitect` provides read-only architecture inspection. The AST analyzer scans Python files for syntax errors, large modules/functions and exact duplicate sources; reports are written under `.zerion/evolution/reports/`. `Optimizer` turns findings into recommendations. Analysis never changes code.

## 4. Upgrade workflow
1. An operator supplies a proposed change set.
2. Planner creates a typed manifest: reason, paths, risk, dependencies, benefit, rollback, complexity.
3. Protected-path validation occurs before staging.
4. Reviewer checks manifest/path equality, Python syntax, module size and unsafe `shell=True`.
5. Only approved changes are written below `.zerion/evolution/staging/<id>`.
6. Tests run. Deployment requires a separate explicit `approved=True` call.

The generator deliberately stages caller-supervised code rather than autonomously inventing or applying edits.

## 5. Testing workflow
`testing.runner` compiles every staged Python file, then runs the existing Phase 4 regression smoke test if present. Architecture validation rejects protected/unsafe paths. Every test result is recorded on a manifest; any empty or failed set blocks deployment. Integration and regression wrappers keep future expansion modular.

## 6. Deployment workflow
Deployment refuses absent approval, protected files, missing staged files, and incomplete/failing tests. It snapshots existing targets (or writes an explicit absence marker for new modules), uses same-directory temporary-file replacement, records a version manifest, tests passed, files changed and rollback ID.

## 7. Rollback workflow
Each deployment has `.zerion/evolution/backups/<id>`. Rollback restores backed-up files and removes newly-created files represented by absence markers. Backup/restore errors surface without silently masking a failed deployment; a deployment exception automatically invokes rollback.

## 8. Security model
Constitution paths are hard-blocked: `main.py`, configuration, prompt, terminal, speech, API, legacy memory, intent, planner, providers, core and `.env`. Unsafe parent/absolute paths are rejected. The system cannot delete protected files, access secrets, install packages, run destructive shell operations, or deploy without direct user approval. It creates reports/proposals only during analysis.

## 9. Performance impact
No startup impact: nothing imports Phase 5 from the terminal loop. Explicit analysis is one local AST walk. Test runs use the current Python interpreter and bounded 15/30-second subprocess timeouts. No persistent processes.

## 10. Resource usage / Termux
Standard library only; lazy construction; small JSON manifests and file-level staged copies. No package installations, embeddings, model downloads or network calls. Work happens only when explicitly requested; background analysis can safely call `EvolutionEngine.analyze()` and generates a report only.

## 11. Readiness score
**90/100 — production-ready supervised evolution foundation.** The policy gate, staging, validation, test enforcement, atomic deployment, manifest versioning and rollback are implemented and smoke-tested. The intentionally withheld 10 points cover future user-facing approval commands, richer project-specific integration tests and measured benchmarks, all of which should remain explicit/supervised.

## Verification
```bash
python -m compileall evolution testing engineering tests
python -c "from tests.test_phase4 import test_phase4; from tests.test_phase5 import test_phase5; test_phase4(); test_phase5()"
```
Result: `Phase 4 + Phase 5 smoke tests: passed`.
