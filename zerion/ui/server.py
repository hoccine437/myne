# ui/server.py
"""Zerion WebUI server — a thin HTTP/WebSocket surface over the Core.

* Static SPA at ``/`` (vanilla ES modules, zero build step).
* ``WS /ws`` streams every Core/UI event (chat, pipeline stages,
  telemetry, planner state, confirmations...) and accepts user input:
  messages, confirmations, terminal commands.
* ``/api/*`` provides read-only panel data (bootstrap, memory, logs,
  filesystem through the Core's own tools) plus the small set of
  runtime-toggleable Core settings (planner / self-critic / voice).

Every state-changing call goes through ``ui.session.ZerionUISession``,
which composes the Core engines exactly like main.py. This file adds no
business logic — it only routes and serializes.

Run:
    cd zerion && python -m ui.server [--host 0.0.0.0] [--port 8765]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# The Core uses package-less imports (``import config``, ``from tools...``)
# rooted at the zerion/ directory — put it on sys.path when launched from
# anywhere else, then serve from there.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

import config
from constitution.constitution import ConstitutionEngine
from speech import speech_status
from tools.manager import tool_manager

from ui.events import bus
from ui.metrics import sample as sample_metrics, latest as latest_metrics
from ui.session import ZerionUISession

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ---------------------------------------------------------------------------
# Core startup (identical to main.py's main(): constitution first, then
# configuration warnings) — done once, before serving.
# ---------------------------------------------------------------------------

ConstitutionEngine.load()
CONFIG_WARNINGS = config.validate()
# Don't print configuration warnings at import: main.py's entry point already
# reports them; standalone `python -m ui.server` prints them in main() below.
# Loud at exactly one entry, quiet when embedded.

session = ZerionUISession()

# Runtime-toggleable Core settings, mirrored into config per read
# (the engines read these attrs each turn, so changes apply live).
SETTABLE_CONFIG = {
    "planner_enabled": ("PLANNER_ENABLED", bool),
    "self_critic_enabled": ("ENABLE_SELF_CRITIC", bool),
    "voice_enabled": ("VOICE_ENABLED", bool),
    "low_confidence_threshold": ("LOW_CONFIDENCE_THRESHOLD", float),
}


def _current_settings() -> dict:
    """Non-secret runtime settings for the client. Never includes keys."""
    return {
        "planner_enabled": bool(config.PLANNER_ENABLED),
        "self_critic_enabled": bool(config.ENABLE_SELF_CRITIC),
        "voice_enabled": bool(config.VOICE_ENABLED),
        "low_confidence_threshold": config.LOW_CONFIDENCE_THRESHOLD,
        "model": config.GEMINI_MODEL,
        "tts_model": config.GEMINI_TTS_MODEL,
        "voice_name": config.VOICE_NAME,
        "provider": config.LLM_PROVIDER,
        "llm_configured": bool(config.GEMINI_API_KEY),
        "tts_supported": config.gemini_tts_supported(),
        "speech_status": speech_status(),
    }


def _bootstrap_payload() -> dict:
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as f:
            version = f.read().strip()
    except Exception:
        version = "unknown"
    try:
        tools = tool_manager.list_tools()
    except Exception:
        tools = []
    return {
        "name": "Zerion",
        "version": version,
        "settings": _current_settings(),
        "tools": tools,
        "config_warnings": CONFIG_WARNINGS,
        "capabilities": {
            "workspaces": sorted(session_workspace_modes()),
            "events": sorted(bus.KNOWN_TYPES),
        },
    }


def session_workspace_modes():
    from ui.session import WORKSPACES
    return WORKSPACES


# ---------------------------------------------------------------------------
# Starlette app (pure-Python ASGI — Termux/ARM64 safe: no native builds)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: Starlette):
    # Prime psutil's cpu_percent baseline (first call always returns 0.0).
    sample_metrics()
    metrics_task = asyncio.create_task(_metrics_loop())
    idle_task = asyncio.create_task(_idle_loop())
    _startup_greeting()
    try:
        yield
    finally:
        for task in (metrics_task, idle_task):
            task.cancel()


# The 24/7 service (runtime/service.py) owns the READY→greeting sequence
# when it hosts the UI; it flips this on before starting the uvicorn
# thread so greeting fire-once semantics live in exactly one place either
# way. Standalone hosting (python -m ui.server) leaves it off.
SUPPRESS_STARTUP_GREETING = False


def _startup_greeting() -> None:
    """READY announcement for the standalone UI server path.

    When Zerion runs under the 24/7 service, runtime/service.py delivers
    the greeting once for the whole system instead — the once-per-startup
    guard in runtime.greeting makes double delivery impossible either way.
    Voice (the Core's speech stack) is used when available; otherwise the
    greeting falls back to a chat message.
    """
    if SUPPRESS_STARTUP_GREETING:
        return
    try:
        from runtime import greeting
        from memory.memory_manager import load_memory

        try:
            memory = load_memory()
        except Exception:
            memory = None

        def to_chat(text: str) -> None:
            bus.emit("chat", {"role": "ai", "text": text, "kind": "system"})

        text = greeting.deliver_startup_greeting(
            memory=memory, text_channel=to_chat, blocking=False)
        if text and greeting.voice_available():
            # voice handled audio; keep a visible copy in the UI as well
            to_chat(text)
    except Exception:
        # a greeting must never affect startup
        bus.emit("notification", {"level": "info", "text": "Zerion Core is online."})


def _q(request: Request, name: str, default, cast=str, lo=None, hi=None):
    """Query-param helper with clamping (replaces FastAPI's Query())."""
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = cast(raw)
    except Exception:
        return default
    if cast is int or cast is float:
        if lo is not None and value < lo:
            value = lo
        if hi is not None and value > hi:
            value = hi
        return value if cast is float else int(value)
    return value


# route handlers are added to this table and bound at the end
_ROUTES = []

def route(path, methods=("GET",)):
    def deco(fn):
        _ROUTES.append(Route(path, fn, methods=list(methods)))
        return fn
    return deco

_clients: set[WebSocket] = set()


async def _metrics_loop() -> None:
    """Emit a telemetry sample every 2s while at least one client is
    connected (idle servers shouldn't burn cycles nobody watches)."""
    while True:
        await asyncio.sleep(2.0)
        if _clients:
            try:
                bus.emit("metrics", await asyncio.to_thread(sample_metrics))
            except Exception:
                pass


async def _idle_loop() -> None:
    """The web equivalent of main.py's bounded idle maintenance: only
    when nobody is mid-turn, at a slow cadence, fully non-fatal."""
    while True:
        await asyncio.sleep(90.0)
        try:
            await asyncio.to_thread(session.idle_tick)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Static SPA
# ---------------------------------------------------------------------------

@route("/")
async def index(request: Request):
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@route("/health")
async def health(request: Request):
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# WebSocket — the primary channel
# ---------------------------------------------------------------------------

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    subscription = await bus.subscribe()
    sender = asyncio.create_task(_ws_sender(websocket, subscription))
    try:
        await websocket.send_json({"seq": 0, "ts": 0, "type": "hello",
                                   "data": _bootstrap_payload()})
        # Replay the recent past so a late-joining client sees state.
        for event in bus.replay():
            await websocket.send_json(event)
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            await _handle_client_message(websocket, message)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _clients.discard(websocket)
        sender.cancel()
        await bus.unsubscribe(subscription)


async def _ws_sender(websocket: WebSocket, subscription) -> None:
    try:
        while True:
            event = await subscription.queue.get()
            await websocket.send_json(event)
    except Exception:
        return


async def _handle_client_message(websocket: WebSocket, message: dict) -> None:
    """Client → Core. Every state-changing type goes through the session,
    which runs the Core pipeline; read-only types are answered inline."""
    mtype = message.get("type")

    if mtype == "message":
        text = str(message.get("text", ""))[:8000]
        if text.strip():
            asyncio.create_task(asyncio.to_thread(session.process_message, text, "chat"))
    elif mtype == "confirm":
        asyncio.create_task(asyncio.to_thread(session.confirm))
    elif mtype == "cancel":
        asyncio.create_task(asyncio.to_thread(session.cancel))
    elif mtype == "terminal":
        command = str(message.get("command", ""))[:2000]
        session.run_terminal_command(command)
    elif mtype == "ping":
        await websocket.send_json({"seq": 0, "ts": 0, "type": "pong", "data": {}})
    elif mtype == "replay":
        try:
            since = int(message.get("since_seq", 0))
        except Exception:
            since = 0
        for event in bus.replay(since_seq=since):
            await websocket.send_json(event)


# ---------------------------------------------------------------------------
# REST panel data
# ---------------------------------------------------------------------------

@route("/api/bootstrap")
async def api_bootstrap(request: Request):
    return JSONResponse(_bootstrap_payload())


@route("/api/status")
async def api_status(request: Request):
    snap = await asyncio.to_thread(session.snapshot)
    # If the 24/7 runtime is supervising this host, surface its heartbeat —
    # read-only, so the UI can show service health without coupling.
    runtime = None
    hb_path = os.path.join(BASE_DIR, "runtime", "run", "heartbeat.json")
    try:
        with open(hb_path, "r", encoding="utf-8") as f:
            runtime = json.load(f)
    except Exception:
        runtime = None
    return JSONResponse({"session": snap, "metrics": latest_metrics(), "runtime": runtime})


@route("/api/memory")
async def api_memory(request: Request):
    from memory.memory_manager import load_memory
    mem = await asyncio.to_thread(load_memory)
    stats = {section: len(mem.get(section, {}) or {})
             for section in ("identity", "preferences", "relationships", "emotional_state")}
    return JSONResponse({"memory": mem, "stats": stats,
                         "path": config.MEMORY_PATH.replace(os.path.expanduser("~"), "~")})


@route("/api/knowledge")
async def api_knowledge(request: Request):
    """Read-only recent knowledge records for the Research workspace /
    Memory Inspector. Uses the Core's knowledge DB as a data source."""
    limit = _q(request, "limit", 40, int, 1, 200)

    def _read():
        try:
            rows = session.knowledge.db.query(
                "SELECT id, layer, category, content, importance, confidence, created_at "
                "FROM records ORDER BY id DESC LIMIT ?", (limit,))
        except Exception:
            return None
        return [dict(r) for r in rows]
    rows = await asyncio.to_thread(_read)
    return JSONResponse({"records": rows or []})


@route("/api/logs")
async def api_logs(request: Request):
    limit = _q(request, "limit", 200, int, 1, 600)
    events = bus.replay()[-limit:]
    return JSONResponse({"events": [
        e for e in events
        if e["type"] in ("log", "stage", "tool", "decision", "notification", "turn", "error")
    ]})


@route("/api/fs/list")
async def api_fs_list(request: Request):
    """Directory listing *through the Core's list_directory tool* —
    enriched per entry with an is-dir flag (pure presentation)."""
    path = _q(request, "path", ".")
    result = await asyncio.to_thread(tool_manager.execute, "list_directory", {"path": path})
    if not result.success:
        return JSONResponse(status_code=404, content={"error": result.message})
    full = os.path.abspath(os.path.expanduser(path))
    entries = []
    for name in (result.data or []):
        try:
            is_dir = os.path.isdir(os.path.join(full, name))
        except Exception:
            is_dir = False
        entries.append({"name": name, "dir": is_dir})
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return JSONResponse({"path": full, "entries": entries})


@route("/api/fs/read")
async def api_fs_read(request: Request):
    """File contents *through the Core's read_file tool* (it applies the
    Core's own 200KB safety cap)."""
    path = _q(request, "path", "")
    if not path:
        return JSONResponse(status_code=400, content={"error": "missing path"})
    result = await asyncio.to_thread(tool_manager.execute, "read_file", {"path": path})
    if not result.success:
        return JSONResponse(status_code=404, content={"error": result.message})
    return JSONResponse({"path": os.path.abspath(os.path.expanduser(path)),
                         "content": result.data or ""})


@route("/api/settings")
async def api_settings_get(request: Request):
    return JSONResponse(_current_settings())


@route("/api/settings", methods=("POST",))
async def api_settings_set(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    """Toggle the small, documented set of runtime Core settings.
    Applies live (the Core reads these module attrs every turn) and
    persists to .env on a best-effort basis so restarts keep them."""
    updated, rejected = {}, []
    for key, value in (payload or {}).items():
        spec = SETTABLE_CONFIG.get(key)
        if spec is None:
            rejected.append(key)
            continue
        attr, caster = spec
        try:
            if caster is bool:
                value = bool(value) if not isinstance(value, str) else \
                    value.strip().lower() in ("1", "true", "yes", "on")
            else:
                value = caster(value)
        except Exception:
            rejected.append(key)
            continue
        setattr(config, attr, value)
        updated[key] = value
        _persist_env(attr, value)
    if updated:
        bus.emit("decision", {"source": "Settings",
                              "text": "Runtime settings updated: " +
                                      ", ".join(f"{k}={v}" for k, v in updated.items())})
    current = _current_settings()
    current["rejected"] = rejected
    return JSONResponse(current)


_ENV_KEYS = {
    "PLANNER_ENABLED": "PLANNER_ENABLED",
    "ENABLE_SELF_CRITIC": "ENABLE_SELF_CRITIC",
    "VOICE_ENABLED": "VOICE_ENABLED",
    "LOW_CONFIDENCE_THRESHOLD": "LOW_CONFIDENCE_THRESHOLD",
}


def _persist_env(attr: str, value) -> None:
    """Best-effort .env write-through. Fully optional: a read-only or
    missing file simply means the change is session-scoped."""
    key = _ENV_KEYS.get(attr)
    if key is None:
        return
    path = os.path.join(BASE_DIR, ".env")
    line = f"{key}={str(value).lower() if isinstance(value, bool) else value}"
    try:
        lines = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        for i, existing in enumerate(lines):
            if existing.split("=", 1)[0].strip() == key:
                lines[i] = line
                break
        else:
            lines.append(line)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


# Static assets last so API/WS routes win.
_ROUTES.append(Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"))

app = Starlette(routes=_ROUTES + [WebSocketRoute("/ws", websocket_endpoint)],
                lifespan=lifespan)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Zerion WebUI server")
    parser.add_argument("--host", default=os.getenv("ZERION_UI_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ZERION_UI_PORT", "8765")))
    parser.add_argument("--log-level", default="warning")
    args = parser.parse_args()

    for warning in CONFIG_WARNINGS:
        print(f"[configuration] {warning}")
    print(f"Zerion UI → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
