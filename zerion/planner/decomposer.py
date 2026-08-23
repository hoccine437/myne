# planner/decomposer.py
"""
Task Decomposer: decides whether a request is simple (answer directly, or
run at most one tool — the existing llm.py contract handles this fine on
its own) or complex (needs multiple ordered steps), and for complex
requests, produces a Plan.

Design choice: this uses exactly ONE additional LLM call to decompose a
complex request into steps — not one call per planning stage (context,
plan, decompose, verify as separate LLM round-trips). On a rate-limited
free-tier model, chaining several LLM calls per turn would be slow and
likely to hit rate limits; a single decomposition call keeps this
practical on Termux with a free API key. Simple requests skip this call
entirely and go straight through the existing llm.get_llm_output() path,
so the common case has zero added latency.
"""

import json

import api
import config
from llm import safe_json_parse as _safe_json_parse
from planner.models import Plan, Task
from tools.manager import tool_manager

_DECOMPOSE_PROMPT = """You are a task planner. Given a user request and a list of \
available tools, decide if it needs multiple ordered steps to complete, or if it's \
simple enough to answer/handle in one step.

Respond with ONLY a JSON object, no other text:

For a SIMPLE request (one step or none, e.g. a question, a single tool call):
{{"complex": false}}

For a COMPLEX request needing multiple ordered steps:
{{
  "complex": true,
  "goal": "short description of the overall goal",
  "tasks": [
    {{"id": 1, "description": "...", "tool_name": "tool_name_or_null", "parameters": {{}}, "depends_on": [], "expected_result": "observable evidence"}},
    {{"id": 2, "description": "...", "tool_name": "tool_name_or_null", "parameters": {{}}, "depends_on": [1], "expected_result": "observable evidence"}}
  ]
}}

Rules:
- Only mark something complex if it genuinely needs 2+ ordered steps (e.g. "search X, \
then save the results, then summarize them"). A single question or single action is \
always simple.
- tool_name must be an exact name from the available tools list, or null if that step \
is pure reasoning/response with no tool.
- depends_on lists the ids of tasks that must finish first.
- Keep plans bounded — 2 to {max_tasks} tasks. Do not over-decompose.
- For each executable task, expected_result must describe evidence that can
  actually be found in the tool result. Never infer completion without it.
- Prefer independent tasks when dependencies are not real; preserve exact
  dependencies when one step needs another's result.

Relevant reasoning context:
{context}

Recent conversation:
{history}

Available tools:
{tools}

User request: "{request}"
"""


def decompose(user_text: str, available_tools: list,
              reasoning_context: dict | None = None,
              recent_history: str = "") -> Plan:
    """
    Decide if `user_text` needs multi-step planning. Returns a Plan —
    for simple requests, a Plan with zero tasks (caller should fall back
    to the normal single-turn llm.get_llm_output() path); for complex
    requests, a Plan with the decomposed tasks.

    Never raises: any failure (network, bad JSON, missing fields) is
    treated as "simple" so the caller safely falls back to normal chat.
    """
    if not user_text or not user_text.strip():
        return Plan(goal="", tasks=[])

    tools_desc = "\n".join(
        f"- {t['name']}: {t['description']}" for t in available_tools
    ) or "(none available)"
    try:
        from cognition.context import assemble
        context_text = assemble(reasoning_context or {})
    except Exception:
        context_text = ""

    prompt = _DECOMPOSE_PROMPT.format(
        max_tasks=config.thinking_plan_max_tasks(),
        context=context_text or "(no additional context)",
        history=recent_history or "(no recent conversation)",
        tools=tools_desc,
        request=user_text,
    )

    try:
        content = api.call_llm(
            "You are a precise task planner. Always respond with valid JSON only.",
            prompt,
        )
    except Exception as e:
        print(f"(planner: decomposition call failed, treating as simple: {e})")
        return Plan(goal="", tasks=[], created_from=user_text)

    parsed = _safe_json_parse(content)
    if not parsed or not parsed.get("complex"):
        return Plan(goal="", tasks=[], created_from=user_text)

    raw_tasks = parsed.get("tasks", [])
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return Plan(goal="", tasks=[], created_from=user_text)

    tasks = []
    for raw in raw_tasks[:config.thinking_plan_max_tasks()]:
        try:
            task_id = int(raw.get("id"))
            tool_name = raw.get("tool_name")
            if tool_name is not None:
                # authority check against the REAL registry, not the ranked
                # decompose-context subset (ranking is a prompt economy, not
                # a permission) — otherwise a correctly chosen tool silently
                # degrades into a reasoning-only pass
                if tool_manager.get_tool(tool_name) is None:
                    tool_name = None  # genuinely unknown → reasoning step
            tasks.append(Task(
                id=task_id,
                description=str(raw.get("description", "")),
                tool_name=tool_name,
                parameters=raw.get("parameters") or {},
                depends_on=[int(d) for d in raw.get("depends_on", [])],
                expected_result=str(raw.get("expected_result", "") or ""),
            ))
        except Exception:
            continue  # skip a malformed task rather than failing the whole plan

    if not tasks:
        return Plan(goal="", tasks=[], created_from=user_text)

    goal = str(parsed.get("goal", user_text))
    return Plan(goal=goal, tasks=tasks, created_from=user_text)
