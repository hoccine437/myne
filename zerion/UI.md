# Zerion WebUI

The official interface for the Zerion Core — an AI Operating System
workspace, not a chatbot.

**One screen. Everything Zerion knows.** There are no tabs to navigate:
a single adaptive workspace watches what the Core is doing and reshapes
itself around the current task.

---

## Quick start

```bash
cd zerion
pip install -r requirements.txt          # Core (requests, python-dotenv)
pip install -r ui/requirements-ui.txt    # UI bridge (starlette + uvicorn)
export GEMINI_API_KEY=...                # optional; the UI runs fully offline otherwise

python main.py                           # official entry — boots this UI by default
# (equivalent explicit forms: python -m ui.server --host 0.0.0.0 --port 8765,
#  or python -m runtime for 24/7 service mode hosting the same UI)
```

Open `http://localhost:8765`. No build step, no frontend tooling — the
client is dependency-free ES modules + CSS.

> The UI degrades gracefully with no API key: command palette, tools,
> confirmations, telemetry, panels and all adaptive behavior keep
> working; model answers report the missing provider — exactly like the
> terminal front end.

## Voice — one authoritative path

Zerion speaks once, on the server: replies are rendered by the Core's
Gemini TTS (`speech.py`), served to the UI as single-use, expiring
`/api/tts/<token>` URLs (`ui/tts.py` service: dedupe by content hash,
rate-limited, TTL tokens, never exposes the API key, never takes a
filesystem path from the client).

`Zerion reply → speech._generate_audio (Core) → WAV → UI <audio> → phone speaker`

Browser speechSynthesis exists ONLY as an explicitly labeled fallback —
the voice-state chip says BROWSER VOICE and never pretends it's Gemini.
Chip states: GEMINI VOICE · VOICE… · BROWSER VOICE · VOICE OFF · VOICE ERROR.

The UI uses the same `GEMINI_API_KEY` as chat for Gemini TTS. Configure one
key in `.env`; there is intentionally no separate `VOICE_API_KEY`, and the
key itself is never sent to the browser.

## Architecture

```
┌────────────────┐   WebSocket /ws + REST /api/*   ┌────────────────────┐
│  Web client     │ ───────────────────────────────▶│  ui/server.py       │
│  (static SPA)   │ ◀── event stream ────────────── │  (FastAPI surface)  │
└────────────────┘                                   └─────────┬──────────┘
                                                                 │
                                                   ui/session.py (adapter)
                                                   ui/events.py  (bus)
                                                                 │
                                          ┌──────────────────────▼─────┐
                                          │  THE CORE — unchanged:      │
                                          │  intent engine · planner ·  │
                                          │  tool manager · llm ·       │
                                          │  knowledge · learning ·     │
                                          │  cognition · intelligence · │
                                          │  constitution · memory      │
                                          └────────────────────────────┘
```

`ui/session.py` mirrors `main.py`'s per-turn pipeline branch-for-branch
and imports session state + the prompt reducer **from `main.py` itself**
(single source of truth). Terminal printing and server-side TTS are the
only replaced pieces — they are the I/O surface, not logic.

### Event contract (`/ws`)

Client → server: `message{text}`, `confirm`, `cancel`, `terminal{command}`,
`ping`, `replay{since_seq}`.

Server → client: every event is `{seq, ts, type, data}`:

| type | meaning |
|---|---|
| `hello` | bootstrap payload (version, settings, tools, capabilities) |
| `core_state` | `idle thinking listening speaking searching coding learning updating error success` |
| `chat` | `{role: user\|ai, text, kind}` |
| `stage` | pipeline stage (`context`, `intent`, `planner`, `llm`, `self_critic`) with status/duration |
| `workspace` | adaptive mode: `chat coding research trading vision automation` |
| `focus` | focus mode on/off + reason |
| `tasks` / `goal` | planner workflow snapshot / goal counters |
| `tool` | execution lifecycle `start confirm end cancelled` |
| `decision` | notable Core decisions (self-critic, policy, settings) |
| `confirm_required` | destructive action pending approval |
| `metrics` | host telemetry sample |
| `agents` | engine activity roster |
| `memory_update` | long-term memory write happened |
| `notification` / `log` / `turn` / `error` / `pong` | toasts, mirror log, turn lifecycle |

The last 600 events are buffered server-side; reconnecting clients replay
what they missed (`replay{since_seq}`), so a dropped connection never
loses state.

### REST

`/api/bootstrap` · `/api/status` · `/api/memory` · `/api/knowledge` ·
`/api/logs` · `/api/fs/list` · `/api/fs/read` · `/api/settings` (GET/POST)

Filesystem endpoints execute **through the Core's tools**
(`list_directory`, `read_file`), inheriting their validation and safety
caps. `POST /api/settings` only accepts the documented runtime-toggleable
config keys (planner, self-critic, voice) and refuses everything else —
secrets are never serialized to clients and never settable over HTTP.

## The workspace adapts itself

The Core's own classification drives the mode (the user never switches):

| Core signal | Workspace shown |
|---|---|
| `python`/`shell` intent, file mutation, exec tools | **Coding** — editor context, execution log, project rail |
| `file` (read), `web`, `memory` intents | **Research** — knowledge base, working notes, memory writes |
| planner (`needs_planning`) | **Automation** — live dependency graph of the workflow |
| market/portfolio language | **Trading** — chart canvas + signal rail (honest empty state until a feed exists) |
| image/vision language or dropped image | **Vision** — stage, zoom/pan, analysis rail |

Difficult tasks (multi-step plans, tool chains) engage **Focus Mode**:
side rails and the dock fold away automatically, and return when the
turn completes.

## Smart layout engine

`core/device.js` classifies the environment live (width, aspect, DPR,
orientation, pointer type, fold hints via `visualViewport.segments`) and
reflects it as `data-*` attributes on `<html>`; CSS performs the actual
layout switch with no reload and no state loss:

- **Phone** — chat-first; status/insight become bottom-sheet/edge-swipe
  drawers; floating panels become sheets.
- **Tablet** — workspace + chat; status in overlay drawers (edge swipes).
- **Laptop/Desktop** — full three-column cockpit.
- **Ultrawide (≥1900px, ≥2:1)** — roomier rails; developer rail can pin
  as a fourth column.
- **Foldables** — short-side-driven classification + segment detection;
  open = tablet, closed = phone, live on fold/unfold.
- **Multi-monitor** — the header's monitor button spawns a dedicated
  `?view=monitor` window (terminal + logs + telemetry, its own socket);
  with the Window Management API granted it lands on the second screen
  automatically, otherwise drag it over.

Fullscreen: `F11` or the header button; optional *auto-fullscreen on
first interaction* in Settings. Where fullscreen is unavailable the fixed
`100dvh` shell already maximizes usable space.

## Gestures & shortcuts

Swipe from screen edges (drawers) · swipe down to dismiss a sheet ·
long-press the Core orb to toggle dictation · drag anywhere to attach
files (images jump straight to Vision) · drag panel headers, resize from
the corner · drag the dock handle to resize; double-click to reset.

`/` or `Ctrl/⌘K` focus the command bar · ``Ctrl+` `` terminal ·
`Ctrl+E/L/M/J` explorer/logs/memory/dev-tools · `Ctrl+,` settings ·
`Esc` closes dialog → panel → drawers · `F11` fullscreen ·
slash commands have full autocomplete (`/help` lists them).

## Accessibility

ARIA roles/labels across regions and controls, visible focus rings,
`aria-live` conversation, skip links, keyboard-complete panel flows,
honors `prefers-reduced-motion`, optional Reduced/Off animations,
High-contrast theme tokens, text scaling (Compact → Extra large), and
all touch targets ≥ 34px.

## Performance

Single rAF render loop for the orb (paused when hidden/off-screen),
DPR-capped canvases, particle budget scaled by device + quality setting,
windowed chat DOM (≤60 nodes), lazy workspace/panel creation, ~0-byte
build (no bundler), reconnect replay instead of reload.

## Settings

Theme (Obsidian/Glacier/Ember/Mono) · language (EN/FR/ES/DE chrome) ·
voice output (browser TTS, voice + rate) · Core planner toggle ·
self-critic toggle · auto fullscreen · animations · FX quality ·
developer mode · text size · high contrast.

## Developer Mode

`Ctrl+J` opens the pipeline view: every stage (`context → intent →
planner → llm → self_critic`) with timings, tool-call history, turn
latency, live FPS, plus the Logs panel mirroring Core events.

## Verification

```bash
# Backend bridge tests (no API key needed)
cd zerion && python -m pytest tests/test_ui_bridge.py -q

# Client smoke test (headless; needs jsdom dev install)
npm install jsdom          # in the repo root, scratch env, or set SMOKE_REQUIRE_BASE
node zerion/ui/smoke/smoke.mjs

# Full Core suite (must stay green — UI is additive)
cd zerion && python -m pytest tests/ -q
```

The smoke test boots the real SPA modules against a stubbed DOM and
drives every event surface: hello handshake, chat, markdown escaping,
gauges, agents, goals, tasks, tools, confirmations, workspace switching,
floating panels, focus mode, connection loss, and 10 device-classification
scenarios (phones, foldables, tablets, laptop, desktop, ultrawide,
portrait/landscape).

## Files

```
ui/
  __init__.py          package doc
  events.py            thread-safe event bus + replay buffer
  session.py           Core session adapter (mirrors main.py's loop)
  metrics.py           host telemetry sampler (psutil + /proc fallback)
  server.py            FastAPI surface: SPA, /ws, /api/*
  requirements-ui.txt  starlette + uvicorn (pure Python, Termux-safe)
  smoke/smoke.mjs      headless client smoke test
  static/
    index.html         app shell
    css/               base · layout · panels · workspace
    js/core/           bus · store · net · device · dom
    js/modules/        orb · chat · status · insight · commandbar ·
                       terminal · workspace (+modes) · floating · panels ·
                       settings · voice · gestures · shortcuts · monitor · i18n
    js/main.js         boot orchestrator (+ built-in layout auditor)
```
