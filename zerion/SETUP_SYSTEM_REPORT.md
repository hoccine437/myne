# Setup System Report

## Files created
- `setup.py`
- `tests/test_setup.py`
- `SETUP_SYSTEM_REPORT.md`

## Files modified
- `config.py`
- `QUICK_RUN.md`
- `REQUIREMENTS.md`

## Installation flow
```text
python setup.py
python main.py
```
`setup.py` is idempotent: it preserves an existing `.env`, checks Python 3.10+, installs missing required Python packages through `requirements.txt`, checks project directories/write access/Constitution integrity, detects Termux/selected API commands, and prints local voice diagnostics.

## Offline voice default
Configuration defaults are now `VOICE_ENABLED=true`, `VOICE_PROVIDER=offline`, and `LOCAL_TTS_ENGINE=termux`. Piper remains selectable through `LOCAL_TTS_ENGINE=piper` and `PIPER_MODEL_PATH`. Missing local voice components return diagnostics and do not require network or stop terminal operation.

## Verification
`tests/test_setup.py` verifies default env creation and non-overwrite behavior. `python setup.py` was executed in this environment: Python/dependencies/project structure/write access/Constitution passed; non-Termux and missing Piper diagnostics were correctly reported.
