# PHONE_SETUP.md — Zerion Phone Installation Contract

Target: a NORMAL Android phone running Termux. Nothing here assumes root,
custom ROMs, or desktop hardware. Every requirement in this document is
referenced by actual code paths in the repository (grep-verifiable).

## 1. Environment requirements

| Requirement | Minimum | Recommended | Evidence |
|---|---|---|---|
| Android | 10+ (Termux current builds support 12+; API 24 baseline) | 13+ | termux-api minimums; Python builds |
| CPU | arm64 (aarch64) | arm64 | live user session on aarch64 |
| RAM | 2 GB free at start | 4 GB | pure-Python stack; no embedded models |
| Storage | 300 MB free | 1 GB | repo + knowledge DB growth |
| Python | 3.10 | 3.12+ | match statement / `str | None` types used |
| Termux | latest from F-Droid/GitHub (NOT the old Play Store build) | — | Termux:API compatibility |

## 2. Packages / binaries

Termux base packages:

    pkg update && pkg install python git
    # voice playback (one of):
    pkg install mpv               # or: paplay / aplay via pulseaudio
    # background integration (optional but recommended):
    pkg install termux-api        # Termux:API package for phone bridges
    # notifications/contacts/sms via Termux:API app (see §4)

Python: `python setup.py` installs Core (requests, python-dotenv) + UI
(`ui/requirements-ui.txt`: starlette, uvicorn). Both pure-Python —
no clang/rust toolchain is required anymore (2026-08-06 fix: psutil and
pydantic-based stacks were removed from the hard requirements).

Node packages: NOT required on the phone. `jsdom` is a development-only
test harness for the UI smoke test (smoke runs on CI/desktop).

## 3. Environment variables

| Variable | Purpose | Required? |
|---|---|---|
| `GEMINI_API_KEY` | Gemini text + TTS | yes for AI answers/voice; local agent/tool paths work without it (offline) |
| `EMAIL_HOST` `EMAIL_USER` `EMAIL_PASSWORD` | IMAP/SMTP connector | optional (email only) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot connector | optional (telegram only) |
| `.env.example` (template) | copied to `.env` by setup | the phone never logs secrets; audit/telemetry scrub them |

All remaining env vars: DEPENDENCY_MANIFEST.md lists them all (audited by
connectivity_audit §5; undocumented env vars fail the audit).

## 4. Android permissions — only what each feature actually uses

| Permission | Used for | When to grant | Gate in code |
|---|---|---|---|
| Storage (app-private) | memory/knowledge/runtime stores | always | `selfcheck.storage` |
| Notifications access | notification intake (phone mailbox incl. social apps) | optional; enables comm phone lane | `PhoneInboxConnector.health()` |
| Contacts | contact_lookup via termux-contact-list | optional | binary-guarded (`TermuxAdapter.has`) |
| SMS / phone calls | sms/call tools | optional, never without explicit user confirm | `phone.dispatch` + constitution gate |
| Camera photo | camera capture tool | optional | binary-guarded |
| Microphone | not used (browser STT is UI-side) | — | n/a |
| Battery-optimization exclusion | 24/7 background service | recommended for full background mode | TERMUX.md guidance + autostart |
| Wake lock (termux-wake-lock) | keeps service alive under Doze | recommended | documented in TERMUX.md |

Permissions never requested: location, contacts-sync beyond lookup,
accessibility global listeners (not used). If a permission is missing, the
matching connector reports `disconnected` honestly — nothing pretends.

## 5. One-procedure setup

    # inside Termux, from a fresh state:
    pkg update && pkg install python git
    git clone <repo> zerion && cd zerion/zerion
    python setup.py                 # installs layers, creates .env, verifies constitution
    # edit .env → GEMINI_API_KEY=...
    python -m runtime --check       # ZERION SYSTEM CHECK — all rows must be PASS/DEGRADED (with reasons)
    python main.py                  # Web UI (or --terminal)

Verification step on the phone: `python -m runtime --check` and
`python -m pytest tests/ -q`. A failing row prints exactly what to fix.

## 6. Background mode (user remains in control)

    python -m runtime --install-autostart termux --yes   # writes ~/.termux/boot/zerion
    termux-wake-lock                                     # hold wake lock (battery rules apply)

Reality rules (documented, not bypassed):
- Android may still kill the process under aggressive battery policies —
  state is WAL-persisted; restart revalidates the outbox before executing
  anything (comms/outbox.py recovery path, tested)
- An open UI is never required for the service
- The emergency stop (command "stop all communication", tool comm_estop,
  UI controls) halts every external action at once

## 7. Optional connectors quick start

    # Telegram: create a bot with @BotFather, set TELEGRAM_BOT_TOKEN, restart the
    # service; connector shows 'authenticated' in the Communication panel
    # Email:    set EMAIL_HOST/EMAIL_USER/EMAIL_PASSWORD (IMAP+SMTP app password);
    # start a background flow: tell Zerion e.g. "reply to people on instagram"

## 8. Known Not-Verified (do not interpret as bugs)

- Physical camera/telephony/SMS: code exists + is permission-gated; verified
  only against binary-presence checks in this CI. On-device behavior needs
  the real binaries (all guarded).
- True 24/7 soak on hardware: heartbeats + supervisor are implemented and
  tested in-sandbox; days-long hardware soak is a device-level validation
  (TERMUX.md documents wake-lock and binding expectations).
