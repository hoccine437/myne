# Mark-X Lite

A lightweight AI assistant with an adaptive Web UI as the default front
end. Same brain (prompt, memory, LLM behavior) as the original Mark-X —
no desktop automation, no platform-specific dependencies. Runs on Android
(Termux), Linux, or any machine with Python 3.10+.

`python main.py` boots the official adaptive UI (browser workspace); a
minimal built-in REPL remains available with `--terminal` for UI-less
hosts (no extra packages needed).

## Features

- Chat with long-term memory (identity, preferences, relationships, mood)
- Multi-turn clarification (asks a follow-up question when info is missing)
- Gemini chat with optional Gemini voice/TTS output
- Optional speech input/output — disabled by default, never required
- Pure terminal UI — works over SSH, in Termux, in any TTY

## Install

```bash
pip install -r requirements.txt
```

## Configure

Set the one Gemini API key as an environment variable, or create a `.env`
file in this folder:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3-flash-lite
VOICE_ENABLED=true
VOICE_PROVIDER=gemini
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts
```

`GEMINI_API_KEY` is shared by both chat and voice/TTS. Configure it once;
there is no separate `VOICE_API_KEY` (and no second provider key) in this
Gemini-only release. The key is read from `.env` without being exposed to the
UI or written to application memory/audit events.

## Run

```bash
python main.py            # default: the adaptive Web UI (browser workspace)
python main.py --terminal # --terminal / --legacy: minimal built-in REPL
python main.py --port 9000  # UI on a custom port (env: ZERION_UI_HOST/PORT also work)
```

Default UI mode prints the URL and tries to open your browser. When the UI
extras aren't installed, main.py degrades to the built-in terminal REPL with
a clear install hint instead of crashing. Type `exit`, `quit`, or `stop` to
end a terminal session. Type `mute` to reset the current conversation context
without exiting.

## Web UI (adaptive workspace)

An official browser interface — an adaptive "AI Operating System" workspace —
is available as an additive layer over this Core (no Core behavior changes;
the UI is a front-end adapter over the same engines):

```bash
pip install -r ui/requirements-ui.txt
python -m ui.server --host 0.0.0.0 --port 8765
```

See [UI.md](UI.md) for architecture, the event contract, and verification.

## 24/7 service runtime

Zerion can run continuously as a long-lived service with heartbeat, health
monitoring, automatic recovery with backoff, single-instance guarding, and a
startup greeting (voice-first, text fallback) delivered once it is READY:

```bash
python -m runtime            # service + web UI
python -m runtime --status   # inspect
python -m runtime --stop     # graceful stop
```

See [RUNTIME.md](RUNTIME.md).

## Voice output (optional)

Voice is off by default. Mark-X Lite speaks replies aloud using Gemini's
native text-to-speech — no local TTS engine required. To enable it:

```bash
export VOICE_ENABLED=true
export GEMINI_API_KEY=your_key_here
python main.py
```

`GEMINI_API_KEY` is the single shared Gemini credential for both chat and
voice/TTS. Set it once; Zerion does not use or expect a separate
`VOICE_API_KEY`. Chat and voice may use different Gemini models, but they
authenticate with this same key.

You also need one command-line audio player on PATH:

```bash
# Termux (Android):
pkg install termux-api

# Linux/desktop:
sudo apt install mpv   # or ffmpeg (ffplay), or alsa-utils (aplay)
```

Optional tuning (all have sensible defaults):

```bash
VOICE_NAME=Kore          # one of Gemini's 30 prebuilt voices
VOICE_SPEED=normal       # normal, slow, or fast
VOICE_CACHE=true         # reuse audio for repeated phrases
```

If the API key, network, or a player is unavailable, Mark-X Lite prints
the reason and keeps working via text only — it will never crash because
voice is missing.

## Think x10

Zerion defaults to a bounded **Think x10** protocol for model-backed turns:

- ten explicit reasoning lenses (goal, constraints, evidence, memory,
  alternatives, dependencies, capability fit, risk, verification, answer quality)
- a larger but capped evidence/context window
- deeper verified planning, up to ten bounded tasks when planning is needed
- the existing critic and approval gates remain active

This is not ten unbounded Gemini requests: the ten-lens pass is local prompt
assembly, so simple local commands remain free and the model is never asked
to expose private chain-of-thought. To use the previous lightweight budget:

```dotenv
THINKING_MODE=off
```

`THINKING_MULTIPLIER` accepts `1`–`10` and defaults to `10` in x10 mode.
See [`DEEP_UNDERSTANDING.md`](DEEP_UNDERSTANDING.md) for the full 19-capability
contract and its honest WIRED/PARTIAL/OWNER-GATED status.

## Project layout

```
main.py              conversation loop, session memory, intent dispatch
llm.py                prompt building + JSON response parsing
api.py                backward-compatible shim over providers/router.py
speech.py             optional Gemini-powered voice output
main.py's main()     official entry: boots the Web UI by default (or the
                      built-in minimal terminal via --terminal)
config.py             environment-based Gemini chat + voice configuration
core/
    logging.py          lightweight leveled/colored logging
providers/              Gemini provider abstraction
    router.py             single interface for Gemini text requests
    gemini.py             official Gemini REST transport
prompt.txt             system prompt (unchanged from original)
memory/
    memory_manager.py  atomic writes, automatic backup, corruption recovery
    memory.json         persisted memory store
tools/                 auto-discovered tool system (see tools/README.md)
    base.py             abstract Tool class + ToolResult
    registry.py         auto-discovers every tool file
    manager.py           loads/validates/executes tools, confirmation flow
    *.py                individual tools — one file per category
planner/               optional multi-step planning engine (see planner/README.md)
    planner.py           top-level orchestrator
    decomposer.py         decides simple vs. multi-step, builds a Plan
    executor.py            runs a Plan's tasks via the Tool Manager
    verifier.py             checks results, decides skip vs. abort
    context.py, goal.py, state.py, models.py
intent/                 classification + zero-LLM-cost fast path (see intent/README.md)
    engine.py             entry point -- classify, then try Fast Planner
    classifier.py          rule-based request classification
    fast_planner.py         zero-LLM handling: memory lookups, safe tool calls
    commands.py             /status /tools /memory /history /goals /debug /help
    history.py               session action log
requirements.txt
```

## Tools

Mark-X Lite can autonomously use tools — checking the time, doing math,
reading/writing files, running code, making HTTP requests, reading
system info — when the LLM decides one is needed. No setup required;
tools are discovered automatically from the `tools/` folder.

Destructive tools (deleting/moving files, running shell or Python code)
always ask for confirmation before executing — reply `confirm` to
proceed, or anything else to cancel.

See [`tools/README.md`](tools/README.md) for the full tool list and the
guide to adding your own.

## Intent Engine (always on, adds zero cost to normal chat)

Before any LLM call, Mark-X Lite classifies your message and — for
memory lookups ("what's my name?") and safe tool requests ("generate a
uuid", "what time is it") — answers immediately with **no LLM call at
all**. Everything else costs exactly the same one LLM call it always
did; this only ever removes cost, never adds it.

Also includes a local command palette that never touches the LLM:

```
/status /tools /memory /history /goals /debug [on|off] /plan /help
```

See [`intent/README.md`](intent/README.md) for the classification rules
and what the Fast Planner will/won't handle on its own (short answer:
never anything destructive — those always go through the LLM + the
existing confirmation flow, unchanged).

## Planning (optional, off by default)

For requests that need multiple ordered steps ("search X, save the
results, then summarize them"), Mark-X Lite can decompose a request into
a plan and execute it step by step, retrying or skipping failed steps
automatically. This costs one extra LLM call per turn, so it's off by
default:

```bash
export PLANNER_ENABLED=true
```

See [`planner/README.md`](planner/README.md) for the full workflow,
failure-recovery policy, and why it's opt-in.

## What changed from the original Mark-X

- Removed the Tkinter desktop GUI (`ui.py`, `face.png`). The interim terminal
  interface (`terminal.py`) was itself retired at the final release: the Web
  UI is now the default front end (`python main.py`), with a minimal built-in
  REPL (`--terminal`) for UI-less hosts.
- Removed `pyautogui`-based desktop automation (`open_app`, `send_message`)
  — this only ever worked on Windows and doesn't belong in a lightweight,
  cross-platform assistant. These intents are now acknowledged politely
  instead of attempted.
- Removed the hardcoded Windows Vosk model path and ElevenLabs TTS key —
  speech is now optional, disabled by default, and never hardcodes a key
  or a local file path.
- Removed SerpAPI web search and the browser-opening weather action —
  both required extra paid API keys and desktop browser access; the model
  now answers these conversationally instead.
- Removed the empty `aircraft_report.py` stub and the duplicate
  `backup/tts.py`.
- Added Gemini as a second supported LLM provider alongside Gemini.
- Core logic — prompt.txt, the memory schema, the JSON output contract,
  and the LLM call/parse flow — is unchanged.

## Notes on removed capabilities

The original project's `open_app`, `send_message`, `weather_report`, and
`search` actions depended on Windows-only automation (`pyautogui`) or paid
third-party APIs (SerpAPI, ElevenLabs) not suited to a lightweight,
cross-platform build. Chat and memory — the core of the assistant — are
fully preserved. If you want to re-add any of these as optional plugins,
`main.py`'s `handle_intent()` function is the single place to extend.
