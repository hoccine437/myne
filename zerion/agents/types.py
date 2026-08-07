# agents/types.py
"""The five agent TYPES — their contracts, not their instances.

Each type fixes an intent profile and a tool whitelist. Whitelists contain
only NON-destructive tools: anything needing confirmation stays on the
supervised (human-approved) path through the main pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentType:
    name: str
    description: str
    #: tools this type may execute through the Tool Manager
    allowed_tools: tuple[str, ...]
    #: whether it may search the knowledge base memory directly
    can_search_memory: bool
    max_parallel: int = 3


AGENT_TYPES: dict[str, AgentType] = {t.name: t for t in (
    AgentType(
        "researcher",
        "gather and correlate information: read files, search, query memory",
        allowed_tools=("read_file", "search_files", "list_directory", "http_get",
                       "text_stats", "calculate"),
        can_search_memory=True,
        max_parallel=4,
    ),
    AgentType(
        "coder",
        "inspect and reason about code/files; executes nothing destructive",
        allowed_tools=("read_file", "search_files", "list_directory",
                       "format_json", "text_stats", "hash_text", "calculate"),
        can_search_memory=True,
        max_parallel=3,
    ),
    AgentType(
        "verifier",
        "validate claims/results: recompute, cross-check, checksum, parse",
        allowed_tools=("calculate", "format_json", "text_stats", "hash_text",
                       "random_number", "read_file"),
        can_search_memory=True,
        max_parallel=4,
    ),
    AgentType(
        "controller",
        "device-facing actions are NEVER autonomous: status/telemetry only "
        "through the phone adapter; effectful control stays with the "
        "supervised phone.dispatch path in main.py",
        allowed_tools=("device_state", "battery_status", "cpu_info", "memory_usage",
                       "network_info", "storage_usage", "system_info", "process_list"),
        can_search_memory=False,
        max_parallel=2,
    ),
    AgentType(
        "monitor",
        "observe the environment over time; read-only probes and clock tools",
        allowed_tools=("get_time", "get_date", "device_state", "cpu_info",
                       "memory_usage", "network_info", "storage_usage"),
        can_search_memory=False,
        max_parallel=2,
    ),
)}


def get_type(name: str) -> AgentType | None:
    return AGENT_TYPES.get((name or "").strip().lower())
