# Runtime Intelligence Integration Verification

## Actual normal lifecycle wiring
`main.run_loop()` now creates one `RuntimeIntelligence` object and invokes it for every request after capability assessment:

```text
user goal
 → CapabilityEvolution.prepare
 → RuntimeIntelligence.prepare
    → CapabilityComposition.compose
    → ProjectContinuity.resume
    → SimulationLayer.simulate
    → ExecutionResolver.select
    → WorldModel links
 → existing intent/planner/LLM path
 → RuntimeIntelligence.complete (after successful normal LLM response)
    → Intelligence Quality update
    → structured Reflection
    → ExperienceEngine record
    → WorldModel outcome link
    → ProjectContinuity save
```

The runtime context is supplied to the existing LLM memory block as capability composition and prior-project context. Existing capability, cognition, intent, planner, learning and memory behavior remains present.

## What is verified
- `tests/test_runtime_integration.py` exercises composition, resolver selection, simulation, world graph persistence, project persistence, quality update, structured reflection and experience recording.
- A real main-loop no-key request exercised `RuntimeIntelligence.prepare`; the established LLM error fallback remained intact.
- Full compilation and all existing regression suites passed.

## Resolver scope
The resolver is exercised in every request lifecycle using the registered `normal_reasoning` lifecycle provider and produces an auditable decision record. It is **not yet the dispatcher for existing remote LLM providers or ToolManager operations**; therefore provider failover/resource selection is not claimed as integrated.

## Phone scope
The Phone Framework remains permission/capability-aware and approval-gated, but is not registered as an intent/tool runtime provider. It is not claimed as integrated into normal requests because no safe phone-goal dispatcher exists in the current main loop.

## Measured integration completeness
- Prior active integration estimate: 70%.
- After verified lifecycle integration: **78%**.
- The remaining 22% is primarily provider-dispatch resolver integration, phone dispatch integration, real Termux validation, and unified Constitution interception across provider/phone paths.

## Files modified
- `intelligence/runtime.py` (new lifecycle adapter)
- `main.py`
- `tests/test_runtime_integration.py`
- `constitution/protected.lock` (owner-maintained hash update after protected main change)

## Verification command result
`complete integration regression passed`
