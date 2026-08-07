# TTS Diagnostic Report

## Detected configuration
- Text model: `GEMINI_MODEL` (default `gemini-3-flash-lite`)
- Speech model: `GEMINI_TTS_MODEL` (default `gemini-2.5-flash-preview-tts`)
- TTS capability guard: **YES** only when the configured speech model name explicitly contains `tts`.

## Pipeline
```text
Final Zerion response text only
→ speech.speak(text)
→ Gemini TTS endpoint using GEMINI_TTS_MODEL
→ PCM/WAV playback
→ offline Termux/Piper fallback on key, model, player, generation, network, quota or API failure
```
The chat system prompt, conversation history, reasoning context, JSON instructions, and user request envelope are not sent by `speech.py` to the TTS endpoint. `_generate_audio()` receives only the final string passed to `speak()`.

## Validation and fallback
- A non-TTS speech model is blocked before a cloud TTS request.
- Startup diagnostics print text model, speech model, and TTS supported YES/NO via `config.validate()`.
- Gemini failure produces a reason and invokes `OfflineVoice`; conversation output continues independently.

## Verification
- Mock online success: final text reaches generated audio/playback path.
- Mock invalid speech model: cloud call is skipped and offline fallback receives only text.
- Existing Gemini voice fallback, runtime pipeline, hardening, Constitution, Phase 4 and Phase 5 regressions passed.
- Real authenticated Gemini TTS model availability/audio output is not verified in this environment.
