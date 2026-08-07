# Production Intelligence Systems Extension

## Added systems
- **Execution Resolver + Provider Registry:** provider-agnostic selection based on availability, historic reliability/confidence, latency/cost and low-battery penalty; alternative providers are evaluated after non-consequential failure. Consequential work never silently falls through to a second effect.
- **Capability Composition:** retrieves arbitrary existing capability records, creates an emergent composition strategy, and persists only successful reusable compositions.
- **Experience + Reflection:** structured execution context, strategy, alternatives, path, outcome, resources, lessons and confidence; reflection supplies worked/failed/why/change/memory/ranking fields.
- **World Model:** additive SQLite relationship graph for concepts, projects, capabilities, tools and experiences.
- **Quality + Health:** continuously updated reliability, latency, cost, confidence and usage metrics; weak evidence is reported, not deleted.
- **Resource-aware planning contracts:** `ResourceState` carries CPU/RAM/battery/charging/network/temperature/permissions for resolver/provider decisions.
- **Project Continuity:** durable first-class project records with objectives, dependencies, progress, decisions and pending work.
- **Simulation:** prediction-only preflight for consequential plans; actual execution remains constitutional and approval-gated.
- **Maintenance:** bounded report-only duplicate cleanup and weak-capability health review.

## Integration boundaries
These components are additive and provider-agnostic. Existing planner/tool/phone execution contracts remain intact; adapters can register their own `ExecutionProvider` without changing cognitive code. The resolver deliberately does not bypass the Constitution, Tool Manager confirmation, Phase 5 testing/deployment, or Phone approval gates.

## Verification
`tests/test_intelligence.py` verifies ranked selection, non-consequential fallback, no consequential failover, and graph persistence. No external command or network action runs.
