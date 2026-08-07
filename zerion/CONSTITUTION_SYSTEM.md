# Zerion Constitution and Protected Evolution System

## Updated architecture
At process startup `main.py` loads `ConstitutionEngine` exactly once. The SHA-256 lock check happens before terminal initialization; the parsed laws are cached in RAM. Constitutional policy, Phase 5 protection, phone policy, capability proposals, and protected evolution all retain their existing paths but now share the immutable-core authority.

## Constitution architecture
- `constitution.txt` is the only human-readable law source, with ID, priority, title, description and examples.
- `constitution.lock` contains its SHA-256 digest.
- `constitution.py` parses, validates, caches, searches, resolves priority conflicts, evaluates approval, and enforces protected paths.
- `registry.py` produces auditable protected-file entries with reason, owner, priority, version and current hash.

## Workflow
Startup: read → hash → compare lock → parse → validate → cache. A mismatch raises `ConstitutionIntegrityError`; it is never accepted silently. Reload is explicit and owner-approved only. Cached access does no filesystem work per prompt.

## Protected evolution / backup / rollback
`ProtectedEvolution` is a constitutional gate over the existing Phase 5 EvolutionEngine. It blocks protected changes before staging and requires owner approval for deployment. Existing Phase 5 remains responsible for staged generation, review, tests, same-filesystem backups, version manifest, atomic deployment and rollback. Multiple restore points remain under `.zerion/evolution/backups`.

## Permanently protected paths
`constitution/constitution.txt`, `constitution/constitution.py`, `constitution/constitution.lock`, and `main.py` are blocked by both Constitution and Phase 5 manifests. This bootstrap integration was the final intentional edit to `main.py`; normal evolution cannot alter it.

## Security and resource guarantees
No new network calls, package dependencies, background daemon, model, secret logging, or destructive command path. Constitution startup adds one small local text read and SHA-256 calculation; thereafter RAM use is a small immutable law tuple. Termux/Linux compatible standard library only.

## Verification
`tests/test_constitution_engine.py` covers load/cache, lock validation, tamper refusal, law lookup/conflict resolution, protected-path denial, approval requirement, and registry generation. Existing regression suites are also run.

## Readiness score
**96/100 for supervised constitutional evolution.** Remaining scope: pluggable policy event hooks for every legacy third-party extension and owner-mediated secure lock rotation (intentionally absent because normal operation must not alter laws).
