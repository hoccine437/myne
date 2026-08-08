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
    # --- specialist extensions (gaps the master map mandates) -------------
    AgentType(
        "architect",
        "repository/dependency analysis, module boundaries, integration planning",
        allowed_tools=("read_file", "search_files", "list_directory", "format_json"),
        can_search_memory=True,
        max_parallel=3,
    ),
    AgentType(
        "tester",
        "bounded test execution + failure extraction; never unlimited compute",
        allowed_tools=("run_pytest", "read_file", "search_files", "list_directory",
                       "text_stats", "calculate"),
        can_search_memory=True,
        max_parallel=2,
    ),
    AgentType(
        "security",
        "vuln/secret/permission audit; read-only by constitution — never writes",
        allowed_tools=("read_file", "search_files", "list_directory", "hash_text",
                       "format_json", "text_stats"),
        can_search_memory=False,   # auditors don't read user memory by default
        max_parallel=3,
    ),
    AgentType(
        "data",
        "parse / transform / validate structured data",
        allowed_tools=("calculate", "format_json", "text_stats", "base64_convert",
                       "hash_text", "read_file", "search_files"),
        can_search_memory=True,
        max_parallel=4,
    ),
    AgentType(
        "finance",
        "market analysis from fetched data; never fabricates positions or returns",
        allowed_tools=("http_get", "read_file", "calculate", "format_json",
                       "text_stats", "search_files"),
        can_search_memory=True,
        max_parallel=2,
    ),
)}


def get_type(name: str) -> AgentType | None:
    return AGENT_TYPES.get((name or "").strip().lower())
