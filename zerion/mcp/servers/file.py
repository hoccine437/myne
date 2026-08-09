# mcp/servers/file.py
"""File adapter: file tools through the Tool Manager (read/search/list —
writes are NOT exposed to the agent lane; they remain on the supervised
confirmation path behind the destructive tool contract)."""

from tools.manager import tool_manager


def _tool(name):
    def handler(parameters):
        r = tool_manager.execute(name, parameters or {})
        return {"success": r.success, "data": r.data,
                "message": r.message, "error": r.error}
    return handler


SERVER = {
    "name": "file",
    "lifecycle": "in-process",
    "capabilities": {
        "file.read":   {"handler": _tool("read_file"),   "tool": 'read_file', "kind": "read",  "timeout_s": 10},
        "file.search": {"handler": _tool("search_files"), "tool": 'search_files', "kind": "read",  "timeout_s": 10},
        "file.list":   {"handler": _tool("list_directory"), "tool": 'list_directory', "kind": "read", "timeout_s": 10},
        # writes deliberately not registered here — destructive FS stays on
        # the supervised (human-confirmed) lane
    },
}
