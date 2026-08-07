# Project Structure

```text
main.py                 Official production entry point (boots the Web UI by default; `--terminal` = built-in minimal REPL)
config.py               Environment configuration and diagnostics
api.py                  Backward-compatible provider shim
llm.py                  Prompt construction and structured response parsing
prompt.txt              Protected system prompt
terminal.py             Terminal input/output
speech.py               Speech facade
speech.py               Gemini-only online speech output
constitution/           Constitution, locks, policy, protected evolution
providers/              Provider implementations, router, dispatch/health
memory/                 Legacy JSON and memory-layer adapters
knowledge/              SQLite knowledge storage/search/ranking
learning/               Experience, reflection, maintenance
capabilities/           Capability records and evolution
cognition/              Goal modes and knowledge-gap detection
intelligence/           Resolver, world model, projects, runtime lifecycle
intent/                 Classification and fast planner
planner/                Goal decomposition, workflow and execution
tools/                  Lazy-discovered tool implementations
phone/                  Termux-aware phone extraction/controllers/dispatch
evolution/              Staged review/test/deploy/rollback/versioning
engineering/            Read-only architecture support helpers
testing/                Staged-evolution test helpers
tests/                  Local regression tests
*.md                    Release, audit, setup and architecture documents
```

## Protected paths

`main.py`, Constitution files, configuration, prompt, speech, API shim, and legacy core directories are protected by the current evolution manifest. See `constitution/constitution.py` and `evolution/manifest.py` for the exact programmatic lists.
