# Unlimited Capability Evolution System

## Migration
New reasoning no longer imports or selects `skills/`. The legacy package remains a compatibility shim for external imports, as approved; it is not part of the request path. `CapabilityEvolution` is goal-first and supplies the prompt with retrieved methods, a compositional strategy, or an explicit capability gap.

## Model
A capability is persisted as open-ended knowledge and experience records, not a registered class or enumerated category. Records carry method, outcome, confidence, usage ranking, tags, stage metadata and experience count. Tags emerge from goal language; no domain list controls acquisition. Retrieval can combine any matching records for a task.

## Evolution
Unknown goals create a low-confidence capability-gap candidate. Successful/failing task outcomes add experience and raise stage evidence over time (`unknown → learning → basic → … → improving`). Idle review identifies weak capability records and creates recommendations only. It performs no network research, package install, code modification, or external experiment.

## Constitutional boundary
Cognition can freely assess, compose, reflect, and propose. Research, experiments, tool use and permanent capability integrations remain subject to existing Constitutional policy and Phase 5 approval/review/test/version/rollback flow.

## Verification
`tests/test_capabilities.py` verifies unknown-gap recognition, open-ended acquisition, retrieval, and experience recording. Existing Phase 4/5, constitutional, phone, and hardening tests remain passing.
