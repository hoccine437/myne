# mcp/servers.py
"""MCP-style capability servers (in-process transport) — REAL adapters over
existing Zerion capabilities. The current deployment target (Termux /
single-process) ships in-process servers; the gateway contract is transport-
agnostic — a future external wire protocol needs only a new adapter module.
No fake servers: every capability maps to a real working call, and every
call still lands on the canonical Core path (tool_manager / knowledge manager
/ comm engine) so Constitution + confirmation flows stay untouchable.

Adapter contract per module in mcp/servers/:

    SERVER = {
      "name": "file",
      "lifecycle": "in-process",
      "capabilities": {
         "<capability>": {
            "handler": callable(parameters: dict) -> dict,
            "kind": "read" | "write" | "exec",
            "timeout_s": float,
            "retry": "transient" | "never",
         }
      }
    }

Drop-in extension contract: add a module under mcp/servers/ defining SERVER
and it is discovered — nothing needs editing anywhere else.
"""
