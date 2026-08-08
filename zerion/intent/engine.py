# intent/engine.py
"""
Intent Engine: the single entry point main.py calls before any LLM work
happens. Classifies the request (zero LLM cost) and, if the Fast Planner
can fully handle it (also zero LLM cost, except MEMORY lookups and
zero/simple-parameter tool calls), returns the answer immediately.

If neither can handle it, returns (classification, None) -- the caller
uses the classification to decide whether to go straight to the normal
llm.get_llm_output() path or escalate to the AI Planner
(planner.planner.handle_request), per the classification's
`needs_planning` flag.

Resolution order (each stage must fail closed to the next):

    classify → Fast Planner → learning triggers → Agent Orchestration
    → (caller) AI Planner / LLM

The Agent Orchestration consult is the runtime integration of
agents/orchestrator.py: it engages ONLY when the request is ordinary chat
(no tool matched, not memory recall, not a command) AND the orchestrator's
own deterministic classifier sees 2+ specialist domains in the request.
Lanes run in parallel under one deadline; the consult is EVIDENCE-GATED —
if no lane returns usable evidence, the turn falls through to the LLM
exactly as before, so orchestration can never answer *worse* than the
model would have. Gated by config.ORCHESTRATION_ENABLED.

Single shared call site: both front ends (main.py's terminal loop and
ui/session.py's bridge) consume this via `classify_and_fast_handle`, so
the two pipelines cannot drift on orchestration behavior.
"""

import config
from intent.classifier import classify
from intent.fast_planner import try_handle as fast_planner_try_handle
from intent.history import action_history
from intent.models import Intent
from tools.manager import tool_manager

_NO_EVIDENCE = "No matching records"

# Tokens that describe the TASK, never the TOPIC — they must not count as
# evidence of relevance. Without this, token-overlap retrieval can return
# unrelated prior records on generic research phrasing, and the consult
# would answer a request with something it never asked about.
_TASK_WORDS = frozenset({
    "research", "compare", "study", "find", "information", "sources",
    "online", "search", "analyze", "analysis", "explain", "describe",
    "topics", "topic", "about", "with", "from", "this", "that", "what",
    "when", "where", "which", "their", "there", "between", "using",
    "process", "works", "working", "nothing", "something", "stored",
    "help", "please", "tell", "give", "show", "need", "want",
})

# Fraction of the request's topic tokens that retrieved evidence must cover
# before the consult may answer in place of the model. One stray overlapping
# word ("python" in an old note) is not coverage of the question.
_EVIDENCE_COVERAGE_MIN = 0.5


def _significant_tokens(text: str) -> set:
    """Topic-carrying words of the request: long enough to disambiguate,
    minus task phrasing. Used to prove retrieved evidence is on-topic."""
    import re
    return {t for t in re.findall(r"[a-z]{4,}", (text or "").lower())
            if t not in _TASK_WORDS}


# Only these layers may ever count as answerable evidence. Everything else
# either quotes past requests verbatim (critiques, reflections, capability
# gap/experience records — the pipeline itself writes a capability record
# containing the CURRENT request text before this consult runs; retrieving
# it back would be the system answering itself with its own echo) or is
# process telemetry. The prompt path's own context build is unaffected —
# this whitelist exists ONLY for the "may the orchestrator answer instead
# of the model" decision.
_SUBSTANTIVE_LAYERS = frozenset({"knowledge", "long_term"})

# Even inside substantive layers, these categories can never answer a
# request: knowledge_gap records are QUESTIONS the curiosity engine stored
# (("What reliable information is needed to solve: <request>?") — they echo
# the current request word for word.
_NON_ANSWER_CATEGORIES = frozenset({"knowledge_gap"})


def _substantive_evidence(aggregate: str) -> str:
    """Filter aggregate lines to real stored knowledge. Lines arrive as
    "[lane] [layer/category, confidence N%] content"."""
    import re
    keep = []
    for line in (aggregate or "").splitlines():
        m = re.search(r"\[([a-z_]+)/([a-z_:*-]+),", line)
        if m and (m.group(1) not in _SUBSTANTIVE_LAYERS
                  or m.group(2) in _NON_ANSWER_CATEGORIES):
            continue
        keep.append(line)
    return "\n".join(keep)


def _evidence_on_topic(goal: str, aggregate: str) -> bool:
    """The exact gate between "agents found something" and "agents found
    something ABOUT THIS REQUEST". Conservative by construction: when the
    request carries no significant tokens, no in-band answer is possible.
    Echo records never qualify (see _substantive_evidence)."""
    tokens = _significant_tokens(goal)
    if not tokens:
        return False
    haystack = _substantive_evidence(aggregate).lower()
    if not haystack.strip():
        return False
    hits = sum(1 for t in tokens if t in haystack)
    return hits / len(tokens) >= _EVIDENCE_COVERAGE_MIN


def process(user_text: str, memory: dict):
    """
    Returns (classification, fast_result). fast_result is a dict (see
    intent/fast_planner.py's try_handle docstring) if the Fast Planner
    fully handled this request, or None if it needs to go to the LLM
    (either the normal chat path or the AI Planner).
    """
    try:
        available_tools = tool_manager.list_tools()
    except Exception:
        available_tools = []

    classification = classify(user_text, available_tools)

    fast_result = None
    try:
        fast_result = fast_planner_try_handle(classification, user_text, memory)
    except Exception as e:
        print(f"(intent engine: fast planner failed, falling back: {e})")
        fast_result = None

    # Learning triggers (learning/triggers.py): explicit "learn X" requests
    # execute the bounded LearningController loop offline; repeated-failure
    # patterns surface a logged signal. Never intercepts ordinary chat.
    if fast_result is None:
        try:
            from learning import triggers
            fast_result = triggers.evaluate(user_text, memory)
        except Exception as e:
            print(f"(intent engine: learning triggers deferred: {e})")
            fast_result = None

    # Agent Orchestration consult (agents/orchestrator.py) — see module
    # docstring for the exact engagement gates. Evidence-gated by design.
    if fast_result is None:
        try:
            fast_result = _maybe_orchestrate(user_text, classification, memory)
        except Exception as e:
            print(f"(intent engine: orchestration consult deferred: {e})")
            fast_result = None

    if fast_result and fast_result.get("tool_used"):
        action_history.record(
            tool_name=fast_result["tool_used"], success=True, duration_seconds=0.0,
        )

    return classification, fast_result


def _maybe_orchestrate(user_text: str, classification, memory: dict):
    """Deterministic specialist consult before paying for the LLM.

    Engagement gates (ALL must hold):
      - config.ORCHESTRATION_ENABLED
      - intent is CHAT (no tool matched, no planner signal, no command,
        no memory recall) — specialist lanes must never pre-empt the
        supervised tool path
      - orchestrator's own classify() finds 2+ specialist types — a bare
        single-domain mention is not a multi-agent task

    Outcome gates (any one):
      - lanes produced usable evidence AND the critic accepted → answer
        directly with the aggregate (zero LLM cost, honest provenance)
      - lanes produced evidence BUT the critic wants revision → inject it
        into the prompt memory as explicitly-uncertain context and let the
        LLM synthesize (no answer replacement)
      - no usable evidence → None (pure fall-through; nothing changes)
    """
    if not config.ORCHESTRATION_ENABLED:
        return None
    if classification is None or classification.intent is not Intent.CHAT:
        return None

    from agents.orchestrator import orchestrator as _orch
    from agents.orchestrator import classify as orch_classify

    types, _reason = orch_classify(user_text)
    if len(types) < 2:
        return None

    result = _orch.run(user_text)
    if not result.get("orchestrated"):
        return None

    lanes = result.get("lanes") or {}
    meaningful = [t for t, c in lanes.items()
                  if (c.get("result") or "").strip()
                  and _NO_EVIDENCE not in str(c.get("result"))]
    if not meaningful:
        return None

    aggregate = result.get("aggregate", "")
    # topic verification: records must actually mention what was asked —
    # protects the LLM baseline from off-topic retrieval noise
    if not _evidence_on_topic(user_text, aggregate):
        return None
    verdict = (result.get("critic") or {}).get("verdict")
    if verdict != "accept":
        # evidence exists but failed internal review — it may inform, never
        # impersonate, the answer: hand it to the model marked as such
        try:
            memory["orchestrated_evidence"] = (
                f"unverified specialist-lane findings (confidence "
                f"{result.get('confidence')}):\n{aggregate[:800]}")
        except Exception:
            pass
        return None

    headline = (
        f"[orchestrated: {', '.join(result.get('agents', []))} — "
        f"critic accepted, confidence {result.get('confidence')}]"
    )
    return {
        "text": f"{headline}\n{aggregate[:1200]}",
        "handled_by": "orchestrator",
        "tool_used": "agent_orchestrate",
        "orchestration": {
            "task_id": result.get("task_id"),
            "agents": result.get("agents"),
            "verdict": verdict,
            "confidence": result.get("confidence"),
            "finished_ms": result.get("finished_ms"),
        },
    }
