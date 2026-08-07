# Mark-X Lite Intent Engine

Classifies every user request before any LLM work happens, and -- for
the requests it's confident enough about -- answers them without an LLM
call at all.

## Request flow (updated)

```
User input
    v
Command Palette   (intent/commands.py)   -- /status /tools /memory ... never touches the LLM
    v (not a command)
Intent Engine      (intent/engine.py)
    v
Request Classifier (intent/classifier.py) -- rule-based, zero LLM cost
    v
Fast Planner        (intent/fast_planner.py) -- zero-LLM-cost handling:
    v                                            MEMORY lookups, safe
    v                                            zero/simple-param tool calls
   handled? -> done, no LLM call at all
    v not handled
classification.needs_planning?
    v yes, and PLANNER_ENABLED         v no (or disabled)
AI Planner (planner/)                  normal single-turn llm.get_llm_output()
    v                                       v
  Answer  <------------------------------------
```

## Why this exists

Before this, every single message -- including "hi" -- cost exactly one
LLM call, and the decision to try multi-step planning was a blunt
word-count heuristic. This adds a genuinely free classification step in
front of that, so:

- Memory lookups ("what's my name?") answer instantly from
  `memory/memory.json`, no LLM call.
- Safe, unambiguous tool requests ("generate a uuid", "what's the CPU
  usage") execute immediately, no LLM call.
- The AI Planner is only tried when the classifier finds real
  multi-step signal (conjunction words like "then", "after that"), not
  just "the message happens to be long."
- Everything else -- the common case, ordinary conversation -- costs
  exactly the same one LLM call it always did. This layer never adds
  cost to the normal chat path; it only removes cost from the cases it
  can safely shortcut.

## Supported intents

`CHAT`, `TOOL`, `MEMORY`, `PLANNER`, `SYSTEM`, `FILE`, `WEB`, `PYTHON`,
`SHELL`, `UNKNOWN` are all implemented. `AGENT` is defined in
`intent/models.py` as a reserved category for future multi-turn
autonomous action, but nothing currently classifies into it or handles
it -- see "Deferred" below.

## Fast Planner: what it will and won't handle

The Fast Planner is deliberately conservative. It only acts without an
LLM call when:

- **MEMORY**: the question is a direct match against an already-known
  memory field (name, a stated preference, etc.). If nothing matches,
  it returns `None` rather than guessing -- the LLM path handles it,
  which can also correctly say "I don't know that about you yet."
- **TOOL** (and its FILE/WEB/PYTHON/SHELL sub-categories): only for
  tools with **zero required parameters** (`get_time`, `system_info`,
  `generate_uuid`, etc.) or the one tool (`calculate`) whose single
  parameter can be safely lifted from trailing text. Anything needing a
  parameter it can't extract with high confidence -- especially
  destructive tools like `delete_file`, `run_shell`, `write_file` --
  is deliberately **not** handled here. Guessing a file path or shell
  command wrong is a real-world mistake with real consequences; the
  Fast Planner would rather fall through to the LLM (which can ask a
  clarifying question, or at minimum extract the value from full
  conversational context) than guess.

This means the safety properties from the Tool System (destructive
tools always require confirmation) and the confirmation flow are
completely unaffected -- the Fast Planner never bypasses them, it just
never reaches them for anything risky in the first place.

## Command Palette

`/status`, `/tools`, `/memory`, `/history`, `/goals`, `/debug [on|off]`,
`/plan`, `/help` are recognized before classification even runs and
handled entirely locally -- they work with no API key configured and no
network available. `/plugins` reports that `tools/` already serves that
role (see "Deferred" below for why there's no separate plugin system).

## Action History

`intent/history.py` keeps an in-memory (session-only, not persisted) log
of every tool execution: name, success/failure, duration, and failure
reason. `/history` surfaces the most recent entries; `/status` surfaces
a summary count.

## Session State

`intent/session_state.py` is a **read-only view**, not a new state
store -- it reads from `main.py`'s existing `SessionMemory`,
`planner.planner`'s `GoalManager`/`PlannerState`, and
`tools.manager.tool_manager`, rather than duplicating that state. This
was a deliberate choice: a second copy of "what's the current goal"
could drift from the original and contradicts the project's own
"avoid duplicated logic" principle.

## Deferred (not built in this pass, and why)

- **Plugin system**: architecturally identical to the existing Tool
  System (auto-discovery from a folder). A second, parallel
  auto-discovery mechanism for "plugins" with no clear boundary from
  "tools" would be duplicated logic, not new capability. `tools/`
  already fills this role -- see `tools/README.md`.
- **Resource Manager** (RAM/CPU/battery/network monitoring with
  automatic "lightweight mode" switching) and **Background Tasks**
  (non-blocking downloads/indexing/monitoring): both require real
  threading/monitoring-loop code running inside the main process. This
  is meaningfully riskier to get right without dedicated review than
  the rest of this pass, so it's being treated as a distinct follow-up
  rather than shipped speculatively.
- **Self-correcting tool-chain fallback** (search -> alt API -> cache ->
  ask LLM): there's currently only one web tool (`http_get`) and no
  cache layer to fall back to. Building a fallback chain for tools that
  don't exist yet would be speculative scaffolding, not working code.
- **Workflow Engine** as a separate reusable-template abstraction: for
  now, its function is covered by the AI Planner's per-request
  decomposition (`planner/decomposer.py`). A distinct "named, reusable
  workflow" system is a reasonable next step once there are enough
  concrete recurring workflows to justify the abstraction.

## Files

| File | Responsibility |
|---|---|
| `models.py` | `Intent` enum, `Classification` -- pure data |
| `classifier.py` | Rule-based classification, zero LLM calls |
| `fast_planner.py` | Zero-LLM-cost handling for MEMORY and safe single-tool requests |
| `commands.py` | Command palette (`/status`, `/tools`, etc.) |
| `history.py` | Action History -- session-only execution log |
| `session_state.py` | Read-only consolidated view over existing session state |
| `engine.py` | Top-level entry point -- `process(user_text, memory)` |
