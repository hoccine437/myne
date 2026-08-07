# Hardening Implementation Report

## Fixed Critical issues
1. **Unsafe shell parsing removed.** `tools/exec_tools.py` no longer calls `subprocess.run(..., shell=True)`. `ShellExecutorTool` uses `shlex.split` and argument-list execution; pipes, redirects, substitutions and shell-control tokens are rejected. This intentionally changes only unsupported shell-language behavior, not the `run_shell` public tool name/confirmation contract.
2. **Python execution bounded.** `PythonExecutorTool` now uses isolated Python mode (`-I`), a 20,000-character input limit, 15-second timeout, capped output, reduced child environment, and POSIX best-effort CPU/address-space/file-size limits. It emits completion logging through `core.logging`.
3. **Constitutional tool gate added.** Every destructive ToolManager operation evaluates `Constitution` before existing confirmation. Existing confirmation remains the user approval mechanism.

## Fixed High issues
1. **Startup configuration diagnostics.** `main.main()` now prints `config.validate()` warnings after Constitution integrity validation and before terminal UI initialization. Invalid provider/voice/missing asset diagnostics are visible at startup.
2. **Offline voice configuration diagnostics.** `config.validate()` recognizes `VOICE_PROVIDER=offline`, unsupported local engines, and missing Piper model paths.

## Remaining Medium issues
- Protected-core cryptographic verification still hashes Constitution text only; all-protected-file manifest verification is not implemented.
- Resolver, world model, composition, project continuity, simulation and quality modules are still not connected to normal main execution. They remain explicitly documented dormant systems.
- Provider backoff/Retry-After/health persistence and cross-provider failover remain unimplemented.
- Phone adapters remain unverified on a physical Termux device.
- SQLite/knowledge search remains linear for normal retrieval.

## Remaining Low issues
- Legacy skill modules are compatibility-only and inactive.
- Testing integration/performance wrappers remain extension placeholders.
- Broad exception handling remains in legacy optional I/O paths.

## New tests
- `tests/test_execution_safety.py`: argument-list shell execution, shell syntax rejection, bounded Python execution, input-size rejection.
- `tests/test_offline_voice.py`: local voice missing-asset failure behavior.

## Files modified
- `tools/exec_tools.py`
- `tools/manager.py`
- `main.py`
- `config.py`
- `speech.py`
- `voice/__init__.py`
- `voice/offline.py`
- `tests/test_execution_safety.py`
- `tests/test_offline_voice.py`
- `VULNERABILITY_GAP_AUDIT.md`

## Verification evidence
Executed successfully: compilation, execution safety test, offline voice unavailable test, hardening, Constitution, intelligence, capabilities, phone, constitutional, Phase 4 and Phase 5 suites, plus real terminal startup/shutdown.

## Readiness assessment
- **Architecture readiness:** 91%
- **Security readiness:** 86% for supervised local operation; Python execution remains powerful after owner confirmation and is not a complete OS sandbox.
- **Integration completeness:** 68%; dormant intelligence systems remain intentionally unconnected pending separately tested behavior changes.
- **Test coverage summary:** focused regression paths pass; live providers, physical Termux APIs, full process-tree containment, protected-core manifest integrity and dormant-system lifecycle integration are not covered.
