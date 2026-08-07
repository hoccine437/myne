# Zerion Lite Requirements and Clean-System Setup Reference

This document reflects the current implementation. Requirements labeled **optional** are not needed for terminal chat, local tests, or a no-key startup.

## Runtime requirements

| Requirement | Status / reason |
|---|---|
| Python **3.10+** | Required by current type-union syntax such as `int | None`. The project was verified here with Python 3.13. |
| Linux or Android Termux | Supported target platforms in current code. Windows/macOS are not documented as supported targets. |
| UTF-8 locale | Source and memory files are opened as UTF-8. |
| Writable project directory | Required for `memory/memory.json`, SQLite knowledge data, `.zerion/` evolution state, and optional voice cache. |
| Network | **Optional**. Required only for configured LLM providers or Gemini online TTS. |

### Android and Termux versions
The source code does **not** enforce a minimum Android version or Termux version. They are therefore not specified as a project requirement. Use a current supported Termux build compatible with your Android device and Python 3.10+.

## Python packages

Install the required packages:

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` currently requires:

```text
requests
python-dotenv
```

Optional Python package referenced by tools:

```bash
python -m pip install psutil
```

Without `psutil`, Linux/Termux resource tools use limited `/proc` fallbacks where implemented; unsupported information is reported unavailable.

## Linux packages and binaries
No Linux system package is required for keyboard-only, no-voice operation beyond Python and a working `pip`.

Optional audio playback binaries detected by `speech.py`:

```text
mpv
ffplay
aplay
paplay
```

Install one with your distribution’s package manager if using online Gemini speech or Piper WAV playback. Zerion does not install system packages automatically.

## Android Termux packages
For Python and core project dependencies:

```bash
pkg update
pkg install python git
python -m pip install -r requirements.txt
```

For Termux:API command integrations used by the phone and speech layers:

```bash
pkg install termux-api
```

The source detects these commands when available:

```text
termux-battery-status
termux-clipboard-get / termux-clipboard-set
termux-camera-photo
termux-media-player
termux-notification
termux-open-url
termux-share
termux-sms-send
termux-telephony-call
termux-torch
termux-tts-speak
termux-volume
termux-wifi-connectioninfo
```

The project gracefully reports unavailable capabilities when these binaries or their Android integration are absent.

## Android permissions
The project does not request Android permissions programmatically. Grant permissions through Android/Termux:API only for capabilities you intend to use. Depending on the chosen Termux:API command and Android version, this can include storage, microphone/TTS, camera, phone/call, SMS, notifications, clipboard, and location/network-related permissions. A denied permission must be treated as an unavailable capability; Zerion should not be assumed to override it.

For shared storage setup in Termux:

```bash
termux-setup-storage
```

This is optional unless you need shared Android storage access.

## Supported provider APIs

| `LLM_PROVIDER` | Required environment variable | Optional model variable |
|---|---|---|
| `gemini` | `GEMINI_API_KEY` | `GEMINI_MODEL` |
| `gpt` | `OPENAI_API_KEY` | `retired provider_MODEL` |
| `deepseek` | `DEEPSEEK_API_KEY` | `DEEPSEEK_MODEL` |

The current default is `gemini`. A missing key does not crash Zerion; normal LLM replies return the existing error fallback.

## `.env` configuration

Create `.env` in the project root. It is intentionally protected from Phase 5 self-evolution.

Minimal online example:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=replace_with_key
VOICE_ENABLED=false
PLANNER_ENABLED=false
```

Provider alternatives:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=replace_with_your_key
GEMINI_MODEL=gemini-3-flash-lite
```

```dotenv
LLM_PROVIDER=gpt
retired provider_API_KEY=replace_with_your_key
retired provider_MODEL=gpt-4o-mini
```

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=replace_with_your_key
DEEPSEEK_MODEL=deepseek-chat
```

Current additional variables:

```dotenv
REQUEST_TIMEOUT=30
MAX_HISTORY=5
PLANNER_ENABLED=false
PLANNER_MIN_WORDS=4
VOICE_ENABLED=false
VOICE_PROVIDER=gemini
VOICE_NAME=Kore
VOICE_SPEED=normal
VOICE_LANGUAGE=auto
VOICE_VOLUME=1.0
VOICE_CACHE=true
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts
```

## Voice requirements

### Online Gemini voice

```dotenv
VOICE_ENABLED=true
VOICE_PROVIDER=gemini
GEMINI_API_KEY=replace_with_your_key
```

Requires network access and one detected player binary: `termux-media-player`, `mpv`, `ffplay`, `aplay`, or `paplay`.


```text
project-root/
├── main.py
├── config.py
├── prompt.txt
├── requirements.txt
├── .env                         # user-created; optional but recommended for online providers
├── memory/
│   └── memory.json
├── constitution/
│   ├── constitution.txt
│   ├── constitution.lock
│   └── protected.lock
├── providers/
├── planner/
├── intent/
├── tools/
├── knowledge/
├── learning/
├── capabilities/
├── cognition/
├── intelligence/
├── phone/
├── evolution/
├── tests/
└── .zerion/                     # generated only after evolution operations
```

## Common installation problems

| Problem | Cause | Resolution |
|---|---|---|
| `ModuleNotFoundError: requests` | Python dependencies missing | `python -m pip install -r requirements.txt` |
| `ModuleNotFoundError: dotenv` | `python-dotenv` missing | `python -m pip install -r requirements.txt` |
| Startup reports API key missing | `.env` absent, unreadable, or key unset | Create `.env` in project root and set the selected provider key |
| Constitution integrity mismatch | Protected core changed after `protected.lock` was generated | Do not edit protected files during normal operation; use owner-maintained integrity workflow before restart |
| No audio player found | Player binary missing | Install/enable a supported player or disable voice |
| `termux-* is unavailable` | Termux:API package/app/permission unavailable | Install `termux-api`, enable corresponding Android permission, then restart Termux if needed |
| Phone action returns unavailable | Android integration/permission unavailable | Treat as unavailable; do not assume the controller succeeded |
| `Permission denied` on shared storage | Android shared storage not configured | Run `termux-setup-storage`, grant Android permission, then use accessible paths |
