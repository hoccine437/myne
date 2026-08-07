# Security Policy

## Supported release line
The current pre-release line is `1.0.0-rc.1`.

## Reporting
Do not post API keys, private memory, phone numbers, or exploit details in public issues. Report security concerns privately to the project maintainer through the repository’s configured private contact channel.

## Security model
- Consequential tools require confirmation.
- Protected evolution requires review, tests, approval, backup and rollback.
- Constitution text and protected core are integrity checked at startup.
- `.env` is protected from automated evolution.

## Known boundaries
Approved Python execution remains powerful within the launching user’s permissions. Physical Android/Termux integrations and live providers require target-environment validation before production trust.
