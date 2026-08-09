# mcp/servers/web.py
"""Web adapter: read-only network fetches (http_get only). posting/writing
is not granted via the agent lane (Constitution: consequential writes need
the supervised path)."""

from tools.manager import tool_manager


def _http_get(parameters):
    r = tool_manager.execute("http_get", {"url": (parameters or {}).get("url", "")})
    return {"success": r.success, "data": r.data, "message": r.message, "error": r.error}


SERVER = {
    "name": "web",
    "lifecycle": "in-process",
    "capabilities": {
        "web.fetch": {"handler": _http_get, "tool": 'http_get', "kind": "read", "timeout_s": 15,
                      "retry": "transient"},
    },
}
