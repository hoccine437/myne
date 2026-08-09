# mcp/servers/system.py
"""System/on-device adapter: stats + clocks + compute. Read-only on the
whole surface; nothing here can mutate host state."""

from tools.manager import tool_manager


def _tool(name):
    def handler(parameters):
        r = tool_manager.execute(name, parameters or {})
        return {"success": r.success, "data": r.data, "message": r.message, "error": r.error}
    return handler


SERVER = {
    "name": "system",
    "lifecycle": "in-process",
    "capabilities": {
        "system.info":    {"handler": _tool("system_info"),  "tool": 'system_info', "kind": "read", "timeout_s": 5},
        "system.cpu":     {"handler": _tool("cpu_info"),     "tool": 'cpu_info', "kind": "read", "timeout_s": 5},
        "system.memory":  {"handler": _tool("memory_usage"), "tool": 'memory_usage', "kind": "read", "timeout_s": 5},
        "system.disk":    {"handler": _tool("storage_usage"), "tool": 'storage_usage', "kind": "read", "timeout_s": 5},
        "system.network": {"handler": _tool("network_info"),  "tool": 'network_info', "kind": "read", "timeout_s": 8},
        "time.now":       {"handler": _tool("get_time"),     "tool": 'get_time', "kind": "read", "timeout_s": 3},
        "time.today":     {"handler": _tool("get_date"),     "tool": 'get_date', "kind": "read", "timeout_s": 3},
        "compute.math":   {"handler": _tool("calculate"),    "tool": 'calculate', "kind": "read", "timeout_s": 5},
        "device.state":   {"handler": _tool("device_state"), "tool": 'device_state', "kind": "read", "timeout_s": 8},
        "device.battery": {"handler": _tool("battery_status"), "tool": 'battery_status', "kind": "read", "timeout_s": 5},
        "system.processes": {"handler": _tool("process_list"), "tool": 'process_list', "kind": "read", "timeout_s": 8},
    },
}
