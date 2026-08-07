# phone/device.py
"""Device awareness — Zerion knows the body it is running on.

This is the Core's read-only answer to "what device am I on?": platform,
architecture, mobile heuristics, screen, memory, storage, battery,
network, and sensor/I/O availability (mic, speaker, camera, touch).

Design rules:
* one place for all host probing — Android specifics never leak into the
  rest of the Core;
* every probe degrades independently and honestly reports `None`/unknown
  rather than guessing;
* no subprocess is spawned unless the binary actually exists (shutil.which
  first), every call is timeout-bounded;
* Termux gets rich answers via Termux:API binaries; desktop Linux gets
  psutil//proc answers; anything else gets honest unknowns.

phone.models.DeviceState stays the typed contract for the phone control
layer; this module's richer dict is the device *environment* profile.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess

try:
    import psutil
    _PSUTIL = True
except Exception:  # environment-dependent
    psutil = None
    _PSUTIL = False


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(cmd: list, timeout: int = 5) -> str | None:
    """Bounded read-only command; None on any failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _termux_json(cmd: str) -> dict | None:
    if not _which(cmd):
        return None
    out = _run([cmd], timeout=8)
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def _proc_meminfo() -> dict:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            return {l.split()[0].rstrip(":"): int(l.split()[1]) * 1024
                    for l in f if len(l.split()) >= 2}
    except Exception:
        return {}


def probe_device() -> dict:
    """Full device profile. Never raises."""
    d = {
        "os": platform.system().lower() or "unknown",
        "os_release": platform.release(),
        "machine": "unknown",
        "arch": "unknown",
        "is_termux": is_termux(),
        "is_android": False,
        "is_mobile": False,
        "hostname_kind": "unknown",
    }
    machine = (platform.machine() or "").lower()
    d["machine"] = machine or "unknown"
    d["arch"] = {"aarch64": "arm64", "armv8l": "arm64", "armv7l": "arm32",
                 "x86_64": "x86_64", "amd64": "x86_64", "i686": "x86"}.get(machine, machine or "unknown")
    if is_termux() or is_android_host():
        d["is_android"] = True
        d["is_mobile"] = True

    d["cpu"] = {"cores": os.cpu_count()}
    if _PSUTIL:
        try:
            freq = psutil.cpu_freq()
            d["cpu"]["freq_mhz"] = int(freq.current) if freq else None
        except Exception:
            pass

    mem = {}
    if _PSUTIL:
        try:
            vm = psutil.virtual_memory()
            mem = {"total": vm.total, "available": vm.available, "percent": vm.percent}
        except Exception:
            pass
    if not mem:
        mi = _proc_meminfo()
        if mi.get("MemTotal"):
            mem = {"total": mi["MemTotal"], "available": mi.get("MemAvailable"),
                   "percent": round((1 - mi.get("MemAvailable", 0) / mi["MemTotal"]) * 100, 1)}
    d["memory"] = mem or None

    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        d["storage"] = {"total": usage.total, "free": usage.free}
    except Exception:
        d["storage"] = None

    battery = None
    if is_termux():
        tj = _termux_json("termux-battery-status")
        if tj:
            battery = {"percent": tj.get("percentage"), "plugged": tj.get("plugged", "").startswith("PLUGGED"),
                       "status": tj.get("status")}
    if battery is None and _PSUTIL:
        try:
            b = psutil.sensors_battery()
            if b is not None:
                battery = {"percent": round(b.percent, 1), "plugged": b.power_plugged}
        except Exception:
            pass
    d["battery"] = battery

    network = None
    if is_termux():
        tj = _termux_json("termux-wifi-connectioninfo")
        if tj:
            network = {"type": "wifi", "ssid": tj.get("ssid"), "link_speed_mbps": tj.get("link_speed")}
    if network is None and _PSUTIL:
        try:
            addrs = psutil.net_if_addrs()
            up = [i for i, v in addrs.items() if v and i != "lo"]
            network = {"interfaces": up[:8]} if up else None
        except Exception:
            pass
    d["network"] = network

    # screen: only reported when genuinely knowable — never guessed
    screen = None
    if is_termux() and _which("dumpsys"):
        size = _run(["dumpsys", "display"], timeout=4)
        if size:
            import re
            m = re.search(r"mPhysicalDisplayInfo.*?(\d{3,4}) x (\d{3,4})[^\d]*.*?density ([\d.]+)", size, re.S)
            if m:
                w, hpx = int(m.group(1)), int(m.group(2))
                screen = {"width": w, "height": hpx, "orientation": "portrait" if hpx >= w else "landscape",
                          "density_dpi": float(m.group(3))}
    if screen is None and _which("xrandr"):
        out = _run(["xrandr", "--current"], timeout=4)
        if out:
            import re
            m = re.search(r"current (\d+) x (\d+)", out)
            if m:
                w, hpx = int(m.group(1)), int(m.group(2))
                screen = {"width": w, "height": hpx,
                          "orientation": "portrait" if hpx >= w else "landscape"}
    d["screen"] = screen

    touch = d["is_mobile"]
    if not touch and os.path.isdir("/dev/input"):
        try:
            touch = any("touch" in n.lower() for n in os.listdir("/dev/input"))
        except Exception:
            pass
    d["input"] = {
        "touch": touch,
        "keyboard": not d["is_mobile"] or os.environ.get("TERM") is not None,
    }

    d["io"] = {
        "microphone": _which("termux-microphone-record") or os.path.exists("/dev/snd") or _which("arecord") or _which("paplay"),
        "speaker": _which("termux-media-player") or _which("mpv") or _which("aplay") or _which("paplay") or _which("ffplay"),
        "camera": _which("termux-camera-photo"),
    }

    d["termux_api"] = is_termux() and _which("termux-battery-status")

    d["lifecycle"] = {
        "foreground_service_supported": is_termux(),  # via termux-wake-lock / Termux:Boot
        "background_restrictions": ("android-doze (partial wakelock recommended)"
                                    if is_termux() else "none"),
    }
    return d


def summary(p: dict) -> str:
    """Human-readable one-liner for responses/chat."""
    def yes(v): return "yes" if v else ("no" if v is False else "unknown")
    kind = "Android/Termux" if p["is_termux"] else p["os"]
    scr = p.get("screen") or {}
    return (f"Device: {kind} ({p['arch']}), cores={p['cpu'].get('cores')}, "
            f"ram={(p.get('memory') or {}).get('total', 0) // (1024**3) or '?'}GB, "
            f"screen={scr.get('width', '?')}x{scr.get('height', '?')} {scr.get('orientation', '')} | "
            f"mic={yes(p['io']['microphone'])} speaker={yes(p['io']['speaker'])} "
            f"camera={yes(p['io']['camera'])} touch={yes(p['input']['touch'])}")


def is_android_host() -> bool:
    return bool(os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"))
