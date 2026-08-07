# tools/system_tools.py
"""
System information tools. None of these are destructive — they only
read state. Each detects what's actually available in the current
environment (Termux vs. plain Linux, psutil installed or not) and
returns a clear "not supported here" result rather than crashing.

psutil is optional: if present, it's used for richer cross-platform
data; if absent, tools fall back to /proc parsing (Linux/Termux) or
report unavailable rather than failing.
"""

import os
import platform
import shutil
import subprocess

from tools.base import Tool, ToolResult

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def _is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


class BatteryStatusTool(Tool):
    name = "battery_status"
    description = "Get the device's battery percentage and charging status, if available."
    parameters = {}

    def available(self) -> bool:
        if _is_termux():
            return shutil.which("termux-battery-status") is not None
        return _HAS_PSUTIL and psutil.sensors_battery() is not None

    def execute(self, parameters: dict) -> ToolResult:
        if _is_termux():
            try:
                import json
                result = subprocess.run(
                    ["termux-battery-status"], capture_output=True, text=True, timeout=10,
                )
                data = json.loads(result.stdout)
                pct = data.get("percentage")
                status = data.get("status", "unknown")
                return ToolResult.ok(data=data, message=f"Battery at {pct}% ({status}).")
            except Exception as e:
                return ToolResult.fail(error="query_failed", message=str(e))

        if _HAS_PSUTIL:
            battery = psutil.sensors_battery()
            if battery is None:
                return ToolResult.fail(error="unsupported", message="No battery detected.")
            state = "charging" if battery.power_plugged else "on battery"
            return ToolResult.ok(
                data={"percent": battery.percent, "plugged": battery.power_plugged},
                message=f"Battery at {battery.percent}% ({state}).",
            )

        return ToolResult.fail(error="unsupported", message="Battery status isn't available on this system.")


class StorageUsageTool(Tool):
    name = "storage_usage"
    description = "Get disk/storage usage for the home directory's filesystem."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        try:
            usage = shutil.disk_usage(os.path.expanduser("~"))
            gb = 1024 ** 3
            data = {
                "total_gb": round(usage.total / gb, 2),
                "used_gb": round(usage.used / gb, 2),
                "free_gb": round(usage.free / gb, 2),
            }
            msg = f"{data['used_gb']}GB used / {data['total_gb']}GB total ({data['free_gb']}GB free)."
            return ToolResult.ok(data=data, message=msg)
        except Exception as e:
            return ToolResult.fail(error="query_failed", message=str(e))


class MemoryUsageTool(Tool):
    name = "memory_usage"
    description = "Get current RAM usage."
    parameters = {}

    def available(self) -> bool:
        return _HAS_PSUTIL or os.path.exists("/proc/meminfo")

    def execute(self, parameters: dict) -> ToolResult:
        if _HAS_PSUTIL:
            vm = psutil.virtual_memory()
            data = {"total_mb": vm.total // (1024**2), "used_mb": vm.used // (1024**2), "percent": vm.percent}
            return ToolResult.ok(data=data, message=f"{data['percent']}% RAM used ({data['used_mb']}MB / {data['total_mb']}MB).")

        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    key, _, rest = line.partition(":")
                    info[key.strip()] = int(rest.strip().split()[0])  # kB
            total_kb = info.get("MemTotal", 0)
            avail_kb = info.get("MemAvailable", 0)
            used_kb = total_kb - avail_kb
            percent = round(used_kb / total_kb * 100, 1) if total_kb else 0
            data = {"total_mb": total_kb // 1024, "used_mb": used_kb // 1024, "percent": percent}
            return ToolResult.ok(data=data, message=f"{percent}% RAM used ({data['used_mb']}MB / {data['total_mb']}MB).")
        except Exception as e:
            return ToolResult.fail(error="query_failed", message=str(e))


class CPUInfoTool(Tool):
    name = "cpu_info"
    description = "Get CPU core count and current usage percentage."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        try:
            cores = os.cpu_count() or 1
            data = {"cores": cores}
            if _HAS_PSUTIL:
                data["usage_percent"] = psutil.cpu_percent(interval=0.3)
                return ToolResult.ok(data=data, message=f"{cores} cores, {data['usage_percent']}% usage.")
            return ToolResult.ok(data=data, message=f"{cores} CPU cores.")
        except Exception as e:
            return ToolResult.fail(error="query_failed", message=str(e))


class NetworkInfoTool(Tool):
    name = "network_info"
    description = "Check whether the device currently has network connectivity."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        import socket
        try:
            socket.create_connection(("1.1.1.1", 53), timeout=3).close()
            return ToolResult.ok(data=True, message="Network is reachable.")
        except OSError:
            return ToolResult.ok(data=False, message="No network connectivity detected.")


class ProcessListTool(Tool):
    name = "process_list"
    description = "List the top running processes by memory usage."
    parameters = {"limit": "how many processes to return (default 10)"}

    def available(self) -> bool:
        return _HAS_PSUTIL

    def execute(self, parameters: dict) -> ToolResult:
        if not _HAS_PSUTIL:
            return ToolResult.fail(error="unsupported", message="psutil isn't installed, so process listing isn't available.")
        try:
            limit = int(parameters.get("limit", 10))
            procs = []
            for p in psutil.process_iter(["pid", "name", "memory_percent"]):
                try:
                    procs.append(p.info)
                except Exception:
                    continue
            procs.sort(key=lambda p: p.get("memory_percent") or 0, reverse=True)
            top = procs[:limit]
            msg = ", ".join(f"{p['name']} (pid {p['pid']})" for p in top)
            return ToolResult.ok(data=top, message=msg or "No processes found.")
        except Exception as e:
            return ToolResult.fail(error="query_failed", message=str(e))


class SystemInfoTool(Tool):
    name = "system_info"
    description = "Get basic OS/platform information (system, release, machine architecture)."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        try:
            data = {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python_version": platform.python_version(),
                "termux": _is_termux(),
            }
            msg = f"{data['system']} {data['release']} ({data['machine']}), Python {data['python_version']}"
            if data["termux"]:
                msg += ", running in Termux"
            return ToolResult.ok(data=data, message=msg)
        except Exception as e:
            return ToolResult.fail(error="query_failed", message=str(e))
