# llm.py
"""
Builds the prompt sent to the LLM, calls the configured provider, and parses
the JSON response into the assistant's internal output contract:

    {
        "intent": str,
        "parameters": dict,
        "needs_clarification": bool,
        "text": str | None,
        "memory_update": dict | None,
    }

This mirrors the original assistant's behavior exactly — only the transport
(api.py) and provider selection (config.py) changed.
"""

import json

import api
import config
from core import logging as log
from tools.manager import tool_manager


def load_system_prompt() -> str:
    """
    Load prompt.txt. On failure, this is an explicit, visible error --
    not a silently-substituted generic fallback string, since a swapped
    personality (even a reasonable-sounding one) would be a much harder
    bug to notice than a loud startup error. The assistant still starts
    (a placeholder is used so the process doesn't crash outright), but
    every log line makes clear that the real prompt failed to load.
    """
    try:
        with open(config.PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        log.error(f"prompt.txt could not be loaded from {config.PROMPT_PATH}: {e}")
        log.error("Running with a placeholder prompt -- the assistant's configured "
                   "personality is NOT active. Fix prompt.txt and restart.")
        return "[PROMPT LOAD FAILED -- placeholder] You are a helpful AI assistant."


def render_prompt(template: str, variables: dict = None) -> str:
    """
    Substitute {{variable_name}} placeholders in the loaded prompt text.
    This is pure string substitution -- it never rewrites prompt.txt on
    disk, and if the file contains no placeholders (true of the current
    prompt.txt), this is a no-op that returns the text unchanged. Lets a
    future prompt.txt reference things like {{user_name}} without any
    code change here; today, with no placeholders in the file, behavior
    is identical to the original static prompt.
    """
    if not variables:
        return template
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


SYSTEM_PROMPT = load_system_prompt()


def safe_json_parse(text: str):
    """Extract and parse a JSON object out of a possibly markdown-wrapped
    LLM response. Returns a dict, or None if the text isn't JSON (which is
    a normal outcome on free-tier models that don't always follow format
    instructions — not an error)."""
    if not text:
        return None

    text = text.strip()

    if "```json" in text:
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        except ValueError:
            pass
    elif "```" in text:
        try:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()
        except ValueError:
            pass

    if "{" not in text or "}" not in text:
        return None

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return None


_NOISE_PREFIXES = ("user safety:", "safety:", "moderation:")


def _clean_plain_text(text: str) -> str:
    """Strip stray moderation/meta lines some models prepend to replies
    when they don't follow the JSON format (e.g. 'User Safety: safe')."""
    if not text:
        return text

    lines = [
        line for line in text.splitlines()
        if line.strip().lower() not in _NOISE_PREFIXES
        and not any(line.strip().lower().startswith(p) for p in _NOISE_PREFIXES)
    ]
    # An all-noise response has no usable assistant content. Return an empty
    # string so the structured response path can provide a safe fallback
    # rather than exposing provider moderation metadata to the user.
    return "\n".join(lines).strip()


def _fallback(text: str) -> dict:
    return {
        "intent": "chat",
        "parameters": {},
        "needs_clarification": False,
        "text": text,
        "memory_update": None,
    }


def _tools_block() -> str:
    """Describe available tools for the LLM to select via the existing
    `intent` field. Additive context only — prompt.txt and the system
    prompt itself are never modified."""
    try:
        tools = tool_manager.list_tools()
    except Exception:
        return ""
    if not tools:
        return ""
    lines = ["Available tools (set intent to a tool name and fill parameters to use one; "
             "use intent \"chat\" for normal conversation):"]
    for t in tools:
        params = ", ".join(t["parameters"].keys()) if t["parameters"] else "none"
        lines.append(f"- {t['name']}: {t['description']} (parameters: {params})")
    return "\n".join(lines)


def get_llm_output(user_text: str, memory_block: dict = None) -> dict:
    if not user_text or not user_text.strip():
        return _fallback("I didn't catch that.")

    memory_str = ""
    if memory_block:
        memory_str = "\n".join(f"{k}: {v}" for k, v in memory_block.items())

    tools_str = _tools_block()

    user_prompt = (
        f'User message: "{user_text}"\n\n'
        f"Known user memory:\n{memory_str if memory_str else 'No memory available'}"
        + (f"\n\n{tools_str}" if tools_str else "")
    )

    # Dynamic variable substitution -- a no-op today since prompt.txt has
    # no {{placeholder}} tokens, but wired in so adding one later needs
    # no code change. The prompt's actual wording/personality is never
    # touched, only optional token substitution.
    rendered_system_prompt = render_prompt(SYSTEM_PROMPT, {"user_name": memory_block.get("user_name", "")} if memory_block else None)

    try:
        content = api.call_llm(rendered_system_prompt, user_prompt)
    except Exception as e:
        log.error(f"LLM call failed: {e}")
        return _fallback("I ran into a system error reaching the AI provider.")

    parsed = safe_json_parse(content)
    if parsed:
        text = parsed.get("text")
        if isinstance(text, str):
            text = _clean_plain_text(text)
        # Some providers emit only a moderation/safety marker inside an
        # otherwise valid JSON envelope. It is metadata, not a response.
        if not text:
            text = "Hello. How can I help?"
        return {
            "intent": parsed.get("intent", "chat"),
            "parameters": parsed.get("parameters", {}),
            "needs_clarification": parsed.get("needs_clarification", False),
            "text": text,
            "memory_update": parsed.get("memory_update"),
        }

    # Model replied in plain text instead of JSON (common on free-tier
    # models). Use the reply as-is, but memory_update is unavailable this
    # turn since there's no structured output to extract it from.
    return _fallback(_clean_plain_text(content))
