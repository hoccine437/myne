# Zerion Lite Quick Run Guide

## 1. Obtain the project

Clone when using the published repository:

The currently published repository contains the project archive. Clone, extract it, and enter the directory containing `main.py`:

```bash
git clone https://github.com/hoccine437/zerionlite.git
cd zerionlite
unzip "mark-x-lite (1).zip"
cd mark-x
```

If your project source is already copied locally, change into the directory containing `main.py` instead:

```bash
cd /path/to/mark-x
```

## 2. Run the idempotent setup installer

```bash
python setup.py
```

Then continue with manual dependency instructions only if setup reports a problem.

## 3. Install Python dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Optional resource-tool enhancement:

```bash
python -m pip install psutil
```

## 4. Configure `.env`

```bash
cat > .env <<'EOF'
LLM_PROVIDER=gemini
GEMINI_API_KEY=replace_with_key
VOICE_ENABLED=false
PLANNER_ENABLED=false
EOF
```

Replace the key before starting. Never commit `.env`.

## 5. Optional online voice

```bash
cat >> .env <<'EOF'
VOICE_ENABLED=true
VOICE_PROVIDER=gemini
GEMINI_API_KEY=replace_with_your_key
EOF
```

Install or enable one supported player: `termux-media-player`, `mpv`, `ffplay`, `aplay`, or `paplay`.


```bash
pkg update
pkg install python git unzip termux-api
termux-setup-storage
python -m pip install -r requirements.txt
```

The `termux-api` package enables the Termux command clients used by optional phone/speech integrations. Android permission prompts depend on device configuration.

## 8. Verify installation

```bash
python -m compileall -q .
python -c "import config; print('\n'.join(config.validate()) or 'configuration has no warnings')"
python -c "from constitution.constitution import ConstitutionEngine; print(ConstitutionEngine.verify_lock())"
```

## 9. Run diagnostics

```bash
python tests/test_hardening.py
python tests/test_constitution_engine.py
python tests/test_phone_extract.py
python tests/test_phone_dispatch.py
python tests/test_gemini_voice_only.py
```

## 10. Start Zerion

```bash
python main.py
```

## 11. First conversation

At the `You:` prompt, enter a normal request:

```text
Explain what this project does.
```

Exit safely with:

```text
exit
```

## 12. Test phone capability routing

This tests the supervised phone lifecycle. On a non-Termux system it should report the integration unavailable rather than claim success.

```text
call +15551234567
confirm
```

## 13. Check Gemini speech configuration

```bash
python -c "import speech; print(speech.speech_status())"
```

Speech is disabled when Gemini TTS credentials, a TTS-capable model, or an audio player are unavailable.

## 14. Run the complete local test suite

```bash
python tests/test_execution_safety.py
python tests/test_gemini_voice_only.py
python tests/test_hardening.py
python tests/test_constitution_engine.py
python tests/test_intelligence.py
python tests/test_capabilities.py
python tests/test_phone.py
python tests/test_phone_extract.py
python tests/test_phone_dispatch.py
python tests/test_constitutional.py
python -c "from tests.test_phase4 import test_phase4; from tests.test_phase5 import test_phase5; test_phase4(); test_phase5(); print('all tests passed')"
```

## 15. Troubleshooting

### Missing provider key

```bash
python -c "import config; print(config.validate())"
```

Set the selected provider API key in `.env`.

### Constitution mismatch

```bash
python -c "from constitution.constitution import ConstitutionEngine; print(ConstitutionEngine.verify_lock())"
```

Do not overwrite Constitution or protected-core files during normal operation. Restore the expected project state or use the owner-maintained integrity workflow.

### Termux API unavailable

```bash
command -v termux-battery-status
command -v termux-telephony-call
```

If missing, install `termux-api` in Termux and verify Android permissions for the requested action.

### Offline voice unavailable

```bash
command -v piper
python -c "from voice.offline import OfflineVoice; print(OfflineVoice().status())"
```

Install Piper separately, set `PIPER_MODEL_PATH`, and ensure a supported player is on PATH.

## 16. Safe shutdown and common commands

Inside Zerion:

```text
exit
quit
stop
```

Useful shell commands:

```bash
python main.py
python -m compileall -q .
python -c "import config; print(config.validate())"
python -c "from constitution.constitution import ConstitutionEngine; print(ConstitutionEngine.verify_lock())"
```
