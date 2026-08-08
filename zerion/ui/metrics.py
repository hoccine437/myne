# ui/metrics.py
"""System telemetry sampler for the Zerion UI's System Status panel.

Presentation-layer telemetry only — this modules observes the host and
streams samples to clients; it changes nothing about how the Core runs.
psutil is used when available (it's the same optional dependency the
Core's own system tools prefer); everything has a /proc-based Linux
fallback so the panel still lights up on Termux-style environments.
"""

from __future__ import annotations

import os
import shutil
import time

try:
    import psutil
except Exception:  # pragma: no cover - environment-dependent
    psutil = None

_started_at = time.time()
_last_net = None          # (ts, bytes_sent, bytes_recv)
_latest: dict = {}


def _proc_meminfo() -> dict:
    out = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    out[parts[0].rstrip(":")] = int(parts[1]) * 1024  # kB → B
    except Exception:
        pass
    return out


def sample() -> dict:
    """Take one telemetry sample. Never raises — every field degrades
    independently so a missing sensor blanks its gauge, not the panel."""
    global _last_net, _latest
    now = time.time()
    data = {
        "ts": now,
        "uptime_s": int(now - _started_at),
        "cpu": {"percent": None, "cores": os.cpu_count(), "freq_mhz": None, "load": None},
        "ram": {"percent": None, "used": None, "total": None},
        "swap": {"percent": None},
        "storage": None,      # populated below for real, never guessed
        "gpu": None,          # never fabricated: None unless detected exists
        "net": {"up_bps": None, "down_bps": None},
        "battery": {"percent": None, "plugged": None},
        "processes": None,
        "platform": os.name,
    }
    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        data["storage"] = {"used": usage.used, "free": usage.free, "total": usage.total}
    except Exception:
        pass

    if psutil is not None:
        try:
            data["cpu"]["percent"] = round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            pass
        try:
            freq = psutil.cpu_freq()
            if freq:
                data["cpu"]["freq_mhz"] = int(freq.current)
        except Exception:
            pass
        try:
            vm = psutil.virtual_memory()
            data["ram"] = {"percent": round(vm.percent, 1), "used": vm.used, "total": vm.total}
        except Exception:
            pass
        try:
            data["swap"]["percent"] = round(psutil.swap_memory().percent, 1)
        except Exception:
            pass
        try:
            net = psutil.net_io_counters()
            if _last_net is not None:
                dt = max(now - _last_net[0], 1e-6)
                data["net"]["up_bps"] = int(max(net.bytes_sent - _last_net[1], 0) / dt * 8)
                data["net"]["down_bps"] = int(max(net.bytes_recv - _last_net[2], 0) / dt * 8)
            _last_net = (now, net.bytes_sent, net.bytes_recv)
        except Exception:
            pass
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                data["battery"] = {"percent": round(batt.percent, 1),
                                   "plugged": batt.power_plugged}
        except Exception:
            pass
        try:
            data["processes"] = len(psutil.pids())
        except Exception:
            pass
        try:
            data["cpu"]["load"] = [round(x, 2) for x in psutil.getloadavg()]
        except Exception:
            pass
    else:
        meminfo = _proc_meminfo()
        total = meminfo.get("MemTotal")
        avail = meminfo.get("MemAvailable")
        if total and avail:
            used = total - avail
            data["ram"] = {"percent": round(used / total * 100, 1),
                           "used": used, "total": total}
        try:
            with open("/proc/loadavg", "r", encoding="utf-8") as f:
                parts = f.read().split()
            data["cpu"]["load"] = [float(x) for x in parts[:3]]
            cores = data["cpu"]["cores"] or 1
            data["cpu"]["percent"] = round(min(parts and float(parts[0]) / cores * 100, 100), 1)
        except Exception:
            pass
        try:
            data["processes"] = sum(1 for n in os.listdir("/proc") if n.isdigit())
        except Exception:
            pass

    _latest = data
    return data


def latest() -> dict:
    """Most recent sample (taken on demand if none yet)."""
    return _latest or sample()
