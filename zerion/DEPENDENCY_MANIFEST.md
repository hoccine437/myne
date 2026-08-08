# Zerion dependency manifest — Termux/Android audit surface

Conventions: `TERMUX SAFE` = installs with plain pip as pure-python or uses
stdlib; `TERMUX SAFE WITH CONFIGURATION` = safe once an env/config knob is
set; `REQUIRES TERMUX PACKAGE` = needs a `pkg install` step;
`ANDROID UNSAFE` = does not build/run on Android (must be avoided);
`DESKTOP ONLY` = fine on desktop but pointless/unbuildable on Termux;
`UNKNOWN` = not verifiable from source (kept out of the load path until known).

```json
{
  "python_min": "3.10",
  "python_packages": [
    {"name": "requests", "version": ">=2.31", "required": true, "tier": "core", "native": false, "classification": "TERMUX SAFE"},
    {"name": "python-dotenv", "version": ">=1.0", "required": true, "tier": "core", "native": false, "classification": "TERMUX SAFE"},
    {"name": "starlette", "version": ">=1.4", "required": false, "tier": "ui", "native": false, "classification": "TERMUX SAFE"},
    {"name": "uvicorn", "version": ">=0.30", "required": false, "tier": "ui", "native": false, "classification": "TERMUX SAFE", "note": "pure asyncio loop; we deliberately do NOT use uvicorn[standard] (uvloop/httptools needs native builds)"},
    {"name": "psutil", "version": ">=5.9", "required": false, "tier": "optional-telemetry", "native": true, "classification": "ANDROID UNSAFE", "note": "build aborts on Termux: 'platform android is not supported'; we fall back to /proc telemetry — install on desktop only"},
    {"name": "pytest", "version": ">=8", "required": false, "tier": "development", "native": false, "classification": "DESKTOP ONLY (test harness)"},
    {"name": "httpx2", "version": ">=2", "required": false, "tier": "development", "native": false, "classification": "DESKTOP ONLY (starlette TestClient transport)"},
    {"name": "websockets", "version": ">=13", "required": false, "tier": "development", "native": false, "classification": "TERMUX SAFE (used by tests and audits only)"},
    {"name": "jsdom", "version": ">=22", "required": false, "tier": "development", "native": true, "classification": "DESKTOP ONLY (node module for the headless smoke test)"}
  ],
  "termux_packages": [
    {"name": "python", "why": "runtime", "required": true, "classification": "REQUIRES TERMUX PACKAGE"},
    {"name": "python-pip", "why": "dependency installs", "required": true, "classification": "REQUIRES TERMUX PACKAGE"},
    {"name": "termux-api", "why": "phone body — provides termux-battery-status, termux-clipboard-get, termux-open-url, termux-media-player, termux-notification, termux-torch, termux-telephony-call, termux-sms-send, termux-camera-photo, termux-share, termux-volume, termux-wifi-connectioninfo, termux-microphone-record, termux-tts-speak", "required": false, "classification": "REQUIRES TERMUX PACKAGE"},
    {"name": "mpv", "why": "voice playback (one of mpv|ffplay|aplay|paplay|termux-media-player)", "required": false, "classification": "REQUIRES TERMUX PACKAGE"},
    {"name": "pbcopy", "why": "desktop clipboard shim (macOS)", "required": false, "classification": "DESKTOP ONLY fallback (clipboard via phone adapter on mobile)"},
    {"name": "xclip", "why": "desktop clipboard shim (X11 Linux)", "required": false, "classification": "DESKTOP ONLY fallback"}
  ],
  "system_executables_expected": [
    {"name": "dumpsys", "why": "optional screen probe on Android", "present_in": "android", "classification": "OPTIONAL (probe guarded by shutil.which)"},
    {"name": "xrandr", "why": "optional screen probe on X11 desktops", "present_in": "desktop", "classification": "DESKTOP ONLY (probe guarded)"},
    {"name": "termux-wallpaper", "why": "legacy probe guard only", "present_in": "termux", "classification": "OPTIONAL"},
    {"name": "pytest", "why": "test runner invoked via `python -m pytest` by tools/test_tools.py", "present_in": "python-package", "classification": "DESKTOP ONLY (development)"}
  ],
  "environment_variables_documented": [
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_TTS_MODEL", "GEMINI_URL(env-derived)",
    "VOICE_ENABLED", "VOICE_PROVIDER", "VOICE_NAME", "VOICE_SPEED", "VOICE_LANGUAGE",
    "VOICE_VOLUME", "VOICE_CACHE", "PLANNER_ENABLED", "PLANNER_MIN_WORDS",
    "ENABLE_SELF_CRITIC", "LOW_CONFIDENCE_THRESHOLD", "MINIMUM_RESPONSE_LENGTH",
    "ORCHESTRATION_ENABLED",
    "MAXIMUM_IMPROVEMENT_ATTEMPTS", "REQUEST_TIMEOUT", "MAX_HISTORY", "LOG_LEVEL",
    "LLM_PROVIDER", "NO_COLOR", "ZERION_UI_HOST", "ZERION_UI_PORT",
    "ZERION_UI_NO_AUTOOPEN", "ZERION_UI_PUBLIC", "ZERION_MAX_AGENTS",
    "ZERION_GREETING", "ZERION_GREETING_ENABLED", "ZERION_GREETING_TIMEOUT",
    "ZERION_HEALTH_INTERVAL", "ZERION_HEARTBEAT_INTERVAL",
    "ZERION_MAINTENANCE_INTERVAL", "ZERION_NETWORK_CHECK_INTERVAL",
    "ZERION_BACKOFF_BASE", "ZERION_BACKOFF_MAX", "ZERION_MAX_RECOVERY_ATTEMPTS",
    "ZERION_RESTART_BUDGET", "ZERION_RESTART_WINDOW", "ZERION_FAILED_REPROBE_FACTOR"
  ],
  "platform_environment_used_but_not_installable": [
    "PREFIX", "TERM", "DISPLAY", "ANDROID_ROOT", "ANDROID_DATA", "PATH"
  ],
  "required_directories": [".", "memory", "knowledge", "runtime/run (created)", ".termux/boot (optional for autostart)"],
  "required_permissions": [
    "filesystem write in project dir (memory/knowledge/runtime stores)",
    "network egress to generativelanguage.googleapis.com (LLM/TTS)",
    "android battery batteryStats via termux-api where available"
  ]
}
```

Install recipe the manifest guarantees:

```bash
pkg update && pkg install -y python python-pip
pip install -r requirements.txt            # core
pip install -r ui/requirements-ui.txt      # UI extras (pure python)
pip install pytest httpx2 websockets       # dev testing (optional)
pkg install termux-api                      # phone body (optional)
pkg install mpv                             # or ffplay/aplay/paplay/termux-media-player
cp .env.example .env && $EDITOR .env       # set GEMINI_API_KEY
python main.py                              # UI default; --terminal for the REPL
```
