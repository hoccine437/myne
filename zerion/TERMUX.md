# Zerion on Android + Termux — installation & verification runbook

Everything below is the exact command record for a clean Termux install.
Physical-device verification is marked NOT VERIFIED where the build
environment cannot prove it (see FINAL_RELEASE.md).

## Environment requirements

- Termux (F-Droid build recommended) on Android 9+
- Storage permission for the project directory
- `termux-api` package + Termux:API app for phone-body capabilities
- `Termux:Boot` app if autostart-after-reboot is desired (explicit opt-in)

## Exact commands (recorded)

```bash
# 1. update package metadata
pkg update && pkg upgrade -y

# 2. required system packages (Python, networking, audio player for voice)
pkg install -y python python-pip termux-api mpv
# (mpv or any of: ffplay / aplay / paplay / termux-media-player — speech
# auto-detects; termux-media-player comes with termux-api)

# 3. project environment
cd $SCRIPT_DIR   # the extracted zerion/ directory
pip install -r requirements.txt            # requests, python-dotenv
pip install -r ui/requirements-ui.txt      # optional UI extras: starlette + uvicorn (pure Python, Termux-safe)

# 4. configure environment
cp .env.example .env
$EDITOR .env        # set GEMINI_API_KEY (required for LLM + Gemini voice)

# 5. startup — choose ONE front door:
./android/termux-start.sh       # Android Web UI (opens Android browser)
ZERION_ANDROID_TERMINAL=1 ./android/termux-start.sh  # minimal phone REPL
python -m ui.server --port 8765   # browser UI explicitly (same as default main.py)
python -m runtime                 # 24/7 service (hosts the UI too)

# 6. optional explicit autostart (never installed silently)
python -m runtime --install-autostart termux --yes
# writes ~/.termux/boot/zerion.sh — requires the Termux:Boot app to take effect
```

## Platform behavior audit result (static + simulated profile)

- dependencies: requests, python-dotenv — pure-Python, pip-installable on
  Termux ARM64, **no native builds required** for the Core (SQLite is Python
  stdlib). The UI extras are pure-Python (starlette + vanilla uvicorn) and
  install on Termux/ARM64 with no compilers. `python setup.py --no-ui`
  provisions the lightest phone-safe profile. **No PyTorch/NumPy/OpenCV/rust
  runtimes anywhere in the dependency graph.**
- `phone.device` correctly detects `is_termux/is_android/is_mobile` and
  reports sensor availability honestly (None/unknown when unprobed)
- runtime health monitor keeps the phone subsystem enabled on Termux
  profiles and reports DEGRADED when binaries are missing — no crash
- phone adapter never spawns a command that `shutil.which` hasn't found;
  every action flows through Constitution + approval gates
- no `shell=True` call sites (AST-verified); exec sandbox uses POSIX rlimits
  guarded by `os.name == 'posix'`
- no desktop-only absolute paths in the Core; memory/knowledge stores are
  project-relative

(The dependency detail now lives in the audit-result section above — the
quick summary: EVERYTHING is pure Python — core and UI extras both install
on Termux with no compilers.)

## Documented operating mode (24/7 on Android)

- **Foreground continuous operation** — supported as-is (`python -m runtime`).
- **Background under battery saving** — requires the wake-lock contained in
  the generated Termux:Boot script (`termux-wake-lock`) and the user's
  exemption from Android's vendor battery whitelists; Android may still
  suspend background work when the screen is off.
- **NOT VERIFIED on hardware** — physical doze behavior, wakelock survival
  rates, and sensory/audio execution need a real device; the architecture
  (health monitor, heartbeat, recovery) is fully verified off-device.
