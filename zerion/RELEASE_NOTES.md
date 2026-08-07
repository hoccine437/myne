# Zerion Lite 1.0.0-rc.1 Release Notes

## Release status
Release candidate for supervised Linux terminal use. Android Termux, physical phone actions, offline Piper playback, and live provider reliability remain unverified on target hardware/accounts.

## Included
- Terminal-first assistant runtime with provider routing.
- Atomic legacy memory persistence and recovery.
- Knowledge, learning, capability, cognition, project and world-model subsystems.
- Constitution text and protected-core integrity checking.
- Approval-gated staged evolution, versioning and rollback.
- Safe argument-list execution tool and bounded Python tool.
- Optional online Gemini TTS and optional offline Piper/Termux TTS adapter.
- Supervised phone intent extraction/dispatch with graceful unavailable-Termux behavior.

## Breaking changes
None intentionally documented for public provider, tool, or main entry APIs. Shell tool no longer accepts shell syntax such as pipes/redirection; it accepts argument-list commands only for safety.

## Known limitations
See `FINAL_HARDENING_REPORT.md`, `PHONE_DISPATCH_PRODUCTION_REPORT.md`, and `VULNERABILITY_GAP_AUDIT.md`.
