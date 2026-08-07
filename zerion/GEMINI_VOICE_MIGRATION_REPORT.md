# Gemini Voice Migration Report

## Migration
Offline voice modules, Piper configuration, Termux TTS integration, offline tests, detection logic, and fallback behavior were removed. Gemini TTS is the only speech provider.

## Configuration
```dotenv
VOICE_ENABLED=true
VOICE_PROVIDER=gemini
VOICE_NAME=Charon
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts
GEMINI_API_KEY=replace_with_key
```
Charon remains the configured calm lower-register Gemini voice. Actual voice quality is API/provider dependent.

## Failure behavior
If Gemini TTS has no key, no player, an invalid TTS model, network failure, quota failure, or API failure, speech logs a clear Gemini reason and Zerion continues in text-only mode. No offline provider is attempted.

## Compatibility
`speak(text)` remains unchanged. Chat, Constitution, approval, and runtime architecture are unchanged.

## Verification
Compilation and regression tests pass; physical Gemini audio remains unverified without credentials/audio hardware.
