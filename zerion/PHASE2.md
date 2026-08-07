# Mark-X Lite — Phase 2: Final Report

Scope note: Phase 2's core components (Intent Engine, Context Manager,
Planner, Goal Manager, Tool Orchestrator) were already built and tested
in earlier passes of this project. This pass audited them against this
spec's exact requirements, found two real gaps -- a first-class Workflow
Engine and actual context relevance ranking -- and built those on top of
the existing architecture, per "do not redesign it, build on top of it."

## 1. Updated architecture

```
User
  |
Command Palette (intent/commands.py) -- bypasses everything below, never touches the LLM
  |
Intent Engine (intent/engine.py)
  |
Request Classifier (intent/classifier.py) -- rule-based, zero LLM cost
  |
Fast Planner (intent/fast_planner.py) -- zero-LLM handling: memory lookups, safe tool calls
  | (not handled)
Context Manager (planner/context.py)
  |
  +-- Context Ranking (planner/ranking.py) -- NEW: trims tools/memory/history to relevant subset
  |
Planner (planner/planner.py)
  |
  +-- Task Decomposer (planner/decomposer.py) -- one LLM call: simple or complex?
  |
  +-- Workflow Engine (planner/workflow.py) -- NEW: Plan viewed as Goal/Status/
  |                                             Required-tools/Execution-order
  |
Execution Engine (planner/executor.py)
  |
Verifier (planner/verifier.py) -- rule-based, checks ToolResult.success
  |
Goal Manager (planner/goal.py)
  |
Tool Manager (tools/manager.py) -- never called directly, always through this
  |
LLM (via api.py -> providers/router.py, Phase 1, untouched)
  |
Answer
```

This matches the spec's requested flow (User -> Intent Engine -> Context
Manager -> Planner -> Workflow Engine -> Goal Manager -> Tool Manager ->
LLM -> Answer), with the addition of the Fast Planner/Command Palette
shortcuts that let the common case (simple chat, memory lookups, safe
single-tool calls) skip everything below Intent Engine entirely -- the
spec itself says "simple requests must bypass planning."

## 2. New files

| Path | Purpose |
|---|---|
| `planner/workflow.py` | `Workflow` and `WorkflowStatus` -- wraps an existing `Plan` (never duplicates it) with Goal/Status/Required-tools/Execution-order. Status is always derived fresh from live task states, so it can never drift out of sync with what actually happened. |
| `planner/ranking.py` | Rule-based (zero-LLM-cost) relevance scoring for tools, memory fields, and conversation history -- the actual mechanism behind "never overload the LLM," which previously wasn't implemented (context.py bundled everything unranked). |

No other new files were needed -- everything else the spec asks for
(Intent Engine, Context Manager, Planner, Goal Manager, Tool
Orchestrator) already existed from earlier work and is reused as-is,
per "reuse existing modules whenever possible."

## 3. Modified files

| File | Change |
|---|---|
| `planner/context.py` | `build_context()` now applies `planner.ranking` to tools/memory/history before returning a `PlanningContext`, instead of passing everything through unranked. |
| `planner/planner.py` | `_debug_print()` now shows the full `Workflow` view (status, required tools, execution order), not just raw task states. Added `current_workflow()` for `/plan` to use. |
| `intent/commands.py` | `/plan` now renders `Workflow` status/required-tools instead of reaching into raw `Plan`/`Task` internals directly. |
| `planner/README.md` | Documented the two new modules. |

Foundation (Phase 1), memory architecture, Provider Router, speech,
prompt personality, and the terminal interface were **not** touched --
confirmed by regression testing (see section 9).

## 4. Intent workflow

Unchanged from the existing implementation (`intent/engine.py`):
classify (rule-based, zero LLM cost) -> Fast Planner attempts zero-LLM
handling for MEMORY lookups and safe zero/simple-parameter tool calls ->
falls through to either the AI Planner (if `classification.needs_planning`
and `PLANNER_ENABLED`) or the normal single-turn chat path. See
`intent/README.md` for the full breakdown -- this pass didn't change
intent classification itself, only what happens once a request reaches
the Planner.

## 5. Context workflow

```
build_context(user_text, minimal_memory, recent_history, current_goal):
  1. tool_manager.list_tools() -- only currently-available tools
  2. ranking.rank_tools(user_text, tools) -- word-overlap scored,
     capped at 12; no-op if already under the cap
  3. ranking.rank_memory(user_text, minimal_memory) -- same scoring,
     capped at 8 fields; no-op if already under the cap
  4. ranking.rank_history(recent_history) -- most recent 5 lines
     (recency, not relevance scoring, for conversation history --
     the last few exchanges are what give a follow-up its meaning)
  5. -> PlanningContext, passed to the Task Decomposer
```

Verified directly: a synthetic 21-tool list correctly ranks a
time-related query's `get_time` tool to the top and trims to 12; a
16-field memory dict correctly keeps the field relevant to the question
asked; a 20-line history correctly trims to the most recent 5.

## 6. Planning workflow

Unchanged in substance from the existing implementation
(`planner/decomposer.py`): one LLM call decides simple-vs-complex and,
for complex requests, returns task descriptions with tool names and
dependencies, which become a `Plan`. What changed this pass: the tool
list the decomposer sees is now the ranked/trimmed list, not the full
unranked set -- fewer, more relevant tokens per decomposition call.

## 7. Workflow execution

Execution logic itself (`planner/executor.py`) is **unchanged** --
sequential, dependency-respecting, retry-once-then-skip-or-abort, pauses
on destructive tools for confirmation. What's new is the *view* on top:
`planner.workflow.from_plan(plan)` gives a `Workflow` with:
- `status`: `NOT_STARTED` / `RUNNING` / `COMPLETED` / `FAILED` /
  `PARTIALLY_COMPLETED`, always computed fresh from task states
- `required_tools`: distinct tool names in first-referenced order
- `execution_order`: a real topological sort of task ids respecting
  dependencies (verified against out-of-order input and a circular-
  dependency case, which safely degrades to id order rather than
  hanging)

## 8. Goal management

Unchanged (`planner/goal.py`) -- tracks current/sub/completed/failed/
future goals, session-only (not persisted, consistent with "never
corrupt memory" -- this state is explicitly kept out of
`memory/memory.json`).

## 9. Failure recovery strategy

Unchanged from the existing implementation: retry-once on tool failure,
cancel dependents of a permanently-failed task, abort the whole plan
after 2+ failures, pause (not fail) on destructive tools pending
confirmation. All of this was already tested in earlier passes and
re-verified working with the new Workflow/ranking layers on top --
see section 11.

## 10. Performance impact

Steady-state cold import: **~128-142ms**, statistically unchanged from
the pre-this-pass baseline (~125-167ms across prior measurements in this
project -- normal run-to-run variance, no real regression). Ranking adds
negligible per-turn cost (simple word-overlap scoring over at most a few
dozen short strings) and is skipped entirely when the tool/memory count
is already under the cap, which is the common case in this environment
(12 available tools here, under the 12-tool cap, so ranking is a no-op
today -- it activates as more tools become available, e.g. on a Termux
device with `termux-api` installed).

## 11. Readiness score: **9/10**

**Verified working, with real tests:**
- `Workflow.status` correctly derived for not-started, running,
  completed, partially-completed, and fully-failed states
- `execution_order` correctly topologically sorts out-of-order task
  lists, and safely handles a circular dependency without hanging
- `required_tools` correctly lists all distinct tools even mid-pause
- Context ranking correctly prioritizes relevant tools/memory/history
  and safely no-ops when under the cap
- `/plan` command shows live workflow status during a paused
  (confirmation-pending) multi-step plan, verified end-to-end through
  `main.py`
- Full multi-step execution (calculate -> get_time) still completes
  correctly with ranking and workflow-wrapping active
- Memory, `prompt.txt` (byte-identical, 1521 chars), and Phase 1's
  provider router all confirmed unaffected

**Docked one point for:**
- Ranking's effectiveness is currently unverified against this specific
  project's *real* tool catalog at scale, since only 12 of 33 registered
  tools are available in this sandbox (the rest need Termux-only
  binaries like `termux-api`) -- the ranking logic itself is proven
  correct via a synthetic 21-tool test, but a live run on a Termux
  device with the full tool set would be worth doing to confirm the cap
  and scoring feel right in practice, not just in isolated tests.
