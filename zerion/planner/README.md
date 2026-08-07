# Mark-X Lite Planning Engine

An optional layer that lets Mark-X Lite handle multi-step requests —
"search X, save the results, then summarize them" — by decomposing them
into an ordered list of tool calls, executing them one at a time through
the existing Tool Manager, and verifying each step before moving on.

**Off by default.** Enable with `PLANNER_ENABLED=true`. See "Why opt-in"
below before turning it on.

## Request flow

```
User input
    ↓
Context Manager   (planner/context.py)   — bundles memory + history + tools
    ↓
Decomposer        (planner/decomposer.py) — one LLM call: simple or complex?
    ↓
   simple? → return None → main.py's existing single-turn chat path runs, unchanged
    ↓
   complex? continue:
    ↓
Execution Engine  (planner/executor.py)  — runs tasks in dependency order
    ↓                                        via tools.manager.tool_manager
Verifier          (planner/verifier.py)  — checks each result, decides
    ↓                                        skip vs. abort on failure
Goal Manager      (planner/goal.py)      — tracks current/completed/failed goal
    ↓
Summary → main.py renders it to the user
```

For a **simple** request (a plain question, or something needing at most
one tool), `planner.handle_request()` returns `None` and main.py falls
through to the exact same `llm.get_llm_output()` single-turn path it
always used — the planner adds nothing to that path except one upfront
"is this simple?" check.

## Why opt-in (`PLANNER_ENABLED=false` by default)

The decomposition step is one additional LLM call, made before the
normal chat call, on *every* turn that isn't skipped by
`PLANNER_MIN_WORDS`. On a free-tier/rate-limited model this roughly
doubles API usage per turn. Given Mark-X Lite targets Termux and
free-tier keys, defaulting this on would make the assistant feel slower
and hit rate limits twice as fast for zero benefit on the vast majority
of turns, which are simple questions. Enable it when you actually want
multi-step task execution:

```bash
export PLANNER_ENABLED=true
export PLANNER_MIN_WORDS=4   # skip decomposition for short messages (default: 4)
```

## Task state machine

Each `Task` (planner/models.py) moves through:

```
PENDING → RUNNING → COMPLETED
                  → FAILED → (retry once) → RUNNING → COMPLETED
                                                     → FAILED → skip or abort
PENDING → CANCELLED   (if a dependency failed/was cancelled)
```

## Failure recovery policy

Implemented in `planner/executor.py` + `planner/verifier.py`:

- A tool that fails is retried **once**.
- If it fails again, it's marked `FAILED`. Any task that depends on it is
  `CANCELLED` (never run).
- The Verifier then decides `skip` (continue with whatever else is still
  runnable) or `abort` (cancel all remaining pending tasks) — it aborts
  once **2 or more** tasks in the same plan have permanently failed,
  since that suggests something structural is wrong (no network, a
  consistently broken tool) rather than one bad step.
- A destructive tool (delete/move/run shell, etc.) pauses the *entire
  plan*, not just that task — `ExecutionPaused` bubbles up to main.py,
  which prompts for confirmation exactly like it already does for a
  single-tool call. Saying "confirm" resumes the plan from that step;
  anything else cancels the whole plan.

## Verification approach

Verification is **rule-based**, not an extra LLM call per task — it
checks the `ToolResult.success` flag (the Tool Manager's own structured
contract) plus a basic sanity check (success claimed but no data/message
is treated as suspicious). Adding an LLM round-trip after every single
tool call would multiply both latency and free-tier rate-limit exposure
by the number of tasks in a plan, and a free-tier model re-judging its
own tool's structured output isn't obviously more reliable than trusting
that structured output directly.

## Debug mode

Disabled by default. Enable programmatically:

```python
from planner import planner as planning_engine
planning_engine.set_debug(True)
```

Prints the goal, each task's state, and the tool used, as execution
proceeds.

## Files

| File | Responsibility |
|---|---|
| `models.py` | `Task`, `Plan`, `TaskState` — pure data, no logic, no imports from other planner files (avoids circular imports) |
| `context.py` | Bundles memory/history/tools into one `PlanningContext` per turn, then relevance-ranks each via `ranking.py` |
| `ranking.py` | Rule-based relevance scoring — trims tools/memory/history to the most relevant subset before they reach the decomposer |
| `workflow.py` | `Workflow` — a `Plan` viewed with Goal/Status/Required-tools/Execution-order; status is always derived from live task state, never tracked separately |
| `decomposer.py` | One LLM call: is this simple or complex? Produces a `Plan` |
| `executor.py` | Runs a `Plan`'s tasks via `tools.manager.tool_manager`, handles retry/pause/cancel |
| `verifier.py` | Checks task results, decides skip-vs-abort on failure |
| `goal.py` | Tracks current/sub/completed/failed/future goals across turns (session-only, not persisted) |
| `state.py` | Tracks the currently active (possibly paused) `Plan` across turns |
| `planner.py` | Top-level orchestrator — the only module main.py imports directly |

## Constraints honored

- **Never calls a tool directly** — every execution goes through
  `tools.manager.tool_manager`, the same manager the non-planned path uses.
- **Never touches memory directly** — `main.py` still owns
  `load_memory()`/`update_memory()`; the planner only receives an
  already-reduced memory dict as context.
- **Never modifies `prompt.txt`** — the decomposer uses its own separate
  system prompt for the one decomposition call; the main assistant
  personality prompt is completely untouched.
- **Every module under 300 lines.**

## Future expansion toward full Zerion architecture

- Per-task LLM verification as an opt-in mode for paid-tier users who
  want higher confidence than the rule-based checks provide.
- Parallel execution of independent tasks (currently strictly
  sequential, even when two tasks have no dependency relationship) —
  would need care around Termux's limited concurrency headroom.
- Persisted goals: `future_goals` currently resets each process restart;
  a long-running objective queue would need a small file store, kept
  separate from `memory/memory.json` to avoid the "never corrupt memory"
  constraint.
- Configurable failure policy per task (currently one global
  retry-once/abort-after-2 rule) once real usage shows which tasks need
  different tolerances.
