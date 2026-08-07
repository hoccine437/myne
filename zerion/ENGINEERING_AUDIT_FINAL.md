# Zerion Lite — Foundation Engineering Audit
**Date:** 2026-08-05 · **Scope:** 155 source/configuration/documentation/test files; 134 Python files. Every Python file was AST-parsed and every repository file outside generated `.zerion`/bytecode state was inventory-read. The audit also ran compilation, runtime import/startup measurement, static security searches, and all supplied regression suites.

## Scorecard
| Area | Score | Assessment |
|---|---:|---|
| Overall architecture | 91/100 | Additive layers are clear; legacy core and new cross-cutting policy still need a single enforcement seam. |
| Security | 83/100 | Strong approval/protected evolution/integrity controls; high-trust shell/Python tools are not sandboxed. |
| Performance | 90/100 | Imports are lazy where it matters; local storage and bounded operations; graph/search scaling is limited. |
| Maintainability | 88/100 | Good package separation/docs; compact one-line Phase 4–6 style and large legacy modules reduce readability. |
| Scalability | 84/100 | Registry/composition/project contracts scale conceptually; knowledge search is Python-side linear. |
| Reliability | 91/100 | Atomic JSON and file writer, WAL DB, backups/rollback, bounded subprocesses; no process-tree containment. |
| Code quality | 87/100 | Compilation/import clean, typed contracts in new systems; uneven annotations and some large methods remain. |
| Production readiness | **91/100 supervised local use** | Suitable for a trusted, supervised terminal owner; not multi-tenant/unattended execution. |
| Future Phase 2 readiness | **89/100** | Safe to extend with tests and policy hooks; resolve listed security/scaling gaps first. |

## Measurements and verification
- `python -m compileall -q .`: passed.
- Runtime import smoke: previously validated 77 runtime modules; current full regression imports all layer entry points successfully.
- `import main` cold-process mean: **0.1509 seconds** (five runs: 0.1338–0.1754s). This measures imports, not interactive/provider startup.
- RAM: no portable resident-set utility is present in this environment. Static estimate is low tens of MB for CPython plus `requests`/SQLite module state; no model, daemon, thread pool, or eager network connection is loaded at startup. Measure on target Termux with `ps`/`/proc` before publishing a numeric SLO.
- Security scan: no executable `eval`, `exec`, pickle, unsafe YAML loader, or `os.system`; one intentional `shell=True` executor remains.
- Tests passed: Constitution engine, intelligence, capability, phone, constitutional, hardening, Phase 4, Phase 5.

## Audit findings ranked by severity
1. **High — arbitrary shell and Python execution are not sandboxed.** They are confirmation-gated, timeout/output bounded, but execute with the owner process privileges; a timeout does not guarantee child-process-tree cleanup. This is a trusted-local-only capability.
2. **High — Constitution is not yet a mandatory call-site gate for every legacy component.** It checks startup integrity, protected evolution, policy/phone paths, but legacy tools/planner/provider router rely on their existing controls rather than an event/policy interceptor. No bypass was added; universal enforcement remains incomplete.
3. **Medium — provider resilience/cost controls are incomplete.** Individual providers retry transport errors once, but no exponential backoff, Retry-After behavior, cross-provider failover, rate-limit budget, or persisted metrics exists in the legacy LLM router.
4. **Medium — knowledge/capability search is linear.** Records are loaded and token-overlap ranked in Python. SQLite FTS is created opportunistically but not used for retrieval, so long-lived stores will degrade.
5. **Medium — generalized external state verification is limited.** Phone and command completion commonly verify process exit rather than Android/UI final state; this is platform constrained.
6. **Medium — staged code test runner compiles generated Python but does not import arbitrary generated modules.** This avoids executing untrusted top-level code, but misses integration/import errors. An isolated test process/container is needed.
7. **Low — large legacy modules.** `main.py` 387 lines, `speech.py` 316, `tools/file_tools.py` 252. Splitting protected/main flow without a compatibility plan is not justified in this pass.
8. **Low — observability is local/log based.** No structured tracing, metric sink, memory-budget counter, or health dashboard. Adding these now would be feature scope.
9. **Low — agent/event-bus claims exceed repository implementation.** No separate persistent Agent Manager or Event Bus package is present. Current task-scoped reasoning modes intentionally avoid persistent agents. Treat these as future integration points, not audited runtime subsystems.

## Improvements implemented in this audit
1. **Fixed a protected-evolution correctness defect** in `constitution/evolution.py`: normal, non-protected changes can now be staged for review/test without premature owner approval, while protected paths remain blocked and owner approval remains mandatory for deployment. This restores the documented Stage → Review → Test → Approval → Deploy lifecycle.
2. **Added regression coverage** for that path: normal staged evolution succeeds; `main.py` staging is denied.
3. **Recompiled and re-ran all regression suites** after the correction.

## Improvements intentionally not implemented
- **Shell/Python sandboxing:** requires an explicit Linux/Termux security product decision (container, uid separation, allowlist, or feature restriction). A fake sandbox would be worse than documenting the trust boundary.
- **Global Constitution hook injection:** requires touching every legacy control path and defining event semantics; do it as a tested migration, not a broad unreviewed audit edit.
- **Provider failover/backoff:** changes remote-call timing/cost and needs provider-specific mock tests and budget policy.
- **FTS graph/search rewrite:** beneficial only after measurement on a realistic memory corpus; current Termux target prioritizes small dependencies.
- **Large-module splitting:** no measurable stability benefit sufficient to justify protected/main flow churn.

## Technical debt and risk change
**Before:** protected staging had a workflow dead-end; invalid config and file-write/confirmation defects had already been corrected in earlier hardening; Constitution coverage was partial.

**After:** staged evolution has a usable safe path with protected target denial and deployment approval intact. Integrity, backup, rollback, and regression checks remain healthy. Remaining risk is concentrated in intentionally powerful execution tools, universal policy coverage, remote-provider resilience, and scale testing—not silent data corruption or unsecured protected evolution.

## Final verdict
**Proceed with controlled future development, not unrestricted deployment.** Preserve the existing architecture. Before adding high-risk capabilities, prioritize: (1) an explicit execution sandbox policy, (2) a universal constitution/policy event gate with compatibility tests, (3) provider failure/backoff tests, and (4) measured retrieval scaling. No UI, personality, API, or feature behavior was redesigned in this audit.
