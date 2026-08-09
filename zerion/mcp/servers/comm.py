# mcp/servers/comm.py
"""Communication adapter for the agent lane: READ-only communication views
(inbox search, health) — drafting/sending are never agent capabilities;
sends stay on the supervised confirmation path."""

from comms.inbox import search as inbox_search, overview as inbox_overview
from comms.registry import connectors as comm_connectors


def _inbox(parameters):
    try:
        rows = inbox_search(str((parameters or {}).get("query", "")), limit=8)
        return {"success": True, "data": rows}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _health(parameters):
    try:
        return {"success": True,
                "data": {"connectors": comm_connectors.health(),
                         "inbox": inbox_overview()}}
    except Exception as e:
        return {"success": False, "error": str(e)}


SERVER = {
    "name": "comm",
    "lifecycle": "in-process",
    "capabilities": {
        "comm.search":  {"handler": _inbox,  "kind": "read", "timeout_s": 8},
        "comm.health":  {"handler": _health, "kind": "read", "timeout_s": 5},
    },
}
