# Zerion on Android / Termux

This is the primary mobile launch path. Zerion does not require a laptop,
Node.js, a desktop browser, X11, or a native ML runtime.

## Install

```bash
pkg update -y
pkg install -y python git termux-api
cd "$HOME"
git clone <your-repository-url> zerion
cd zerion/zerion
python setup.py                  # core + mobile Web UI dependencies
cp .env.example .env
nano .env                         # set the shared GEMINI_API_KEY
```

For server-side Gemini voice output, install an Android audio player exposed
to Termux (for example `mpv`) or use the Termux media player from
`termux-api`. The text and UI paths do not require an audio player.

## Start

```bash
# Mobile Web UI; termux-open-url opens Android's browser when available
./android/termux-start.sh

# Terminal-only mode for the lightest phone profile
ZERION_ANDROID_TERMINAL=1 ./android/termux-start.sh
```

The UI listens on `0.0.0.0:8765` and is opened through Android's browser. The
Core and Web UI are the same pipeline; this is not a separate laptop system.

## Learning on the phone

```text
learn kali linux
```

With `GEMINI_API_KEY`, the same Gemini key used by chat and voice creates a
bounded, topic-specific lesson and recall checks. Without a key, Termux may
fetch a bounded public topic summary when network access is available, or you
can provide source material through the `learn_domain` tool. All acquired
material stays **UNVERIFIED** until independent evidence or tested recall
promotes it; Zerion will not claim Kali Linux mastery because an arithmetic
exercise passed.

For 24/7 foreground/background operation, install Termux:Boot and use:

```bash
python -m runtime --install-autostart termux --yes
termux-wake-lock
```

Android battery optimization and physical Termux:API/audio behaviour remain
device-specific and must be verified on the target phone.
