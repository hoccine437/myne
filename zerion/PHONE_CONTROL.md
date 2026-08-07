# Phone Control Framework

## Design
`PhoneIntelligence` is a goal-first, capability-aware layer. It discovers installed Termux:API integrations, snapshots only available capabilities, creates a proposed `PhonePlan`, then requires explicit approval for consequential device effects. It does not expose a blind command palette or assume permissions.

## Current Termux capability adapters
The framework conditionally discovers clipboard, URL launch, battery/Wi-Fi state, notifications, media, camera, torch, telephony calls, SMS, sharing, and volume commands. Every command uses an argument list (never `shell=True`), bounded timeout, capped output, and normalizes failure to `ActionResult`.

Controllers are modular: system, media, communication, camera, notification, and clipboard. Application/accessibility/gallery/file/storage/input/network extensions can be added as controllers without changing planning, constitutional policy, verification, or learning contracts. Android does not provide generic UI automation/foreground-app/notification-reading privileges through ordinary Termux APIs; those capabilities are intentionally unavailable until a permissioned integration exists.

## Governance and learning
Cognitive planning is free and local. Calls, SMS, camera, URL launch, clipboard write, media/system changes, and all effects marked consequential require `approved=True`. The Constitution remains authoritative. `record()` sends outcomes to the existing Learning Engine; it does not record clipboard, notification, contacts, or media contents automatically.

## Verification
`tests/test_phone.py` covers capability-aware plan construction and approval refusal. No live phone action is performed by the test.
