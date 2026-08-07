# Memory Intelligence v1

## Architecture
`memory/intelligence.py` is an additive facade over the existing Knowledge Database and World Model. It does not create another database or replace legacy JSON memory, learning, reflection, experience, capability, or runtime systems. Runtime Intelligence retrieves ranked memory before response completion and stores an episodic record after a normal completed response.

## Lifecycle
Captured → Reviewed → Verified/Hypothesis → Consolidated → Frequently Used → Archived. Archived records remain stored and recoverable. Consolidation only archives inactive, low-importance, low-confidence, unused records; it does not delete verified records.

## Retrieval and confidence
Retrieval uses existing ranked knowledge search with active-goal context, then confidence and importance ordering. Records carry type, source, evidence, timestamps, related-memory metadata, status and confidence history. Inferences use `hypothesis` status and remain separate from facts.

## Procedures, episodes and relationships
Procedures store workflow, tools, prerequisites and verification evidence. Episodes store goal, context, actions, outcome and lessons. Related records are linked through the existing World Model with weighted edges.

## Performance and limitations
Consolidation is bounded by a caller-provided limit and performs no deletion. Similarity remains based on existing lightweight token ranking; semantic embeddings, automatic contradiction detection, multi-task working-memory orchestration and confidence-history mutation are not claimed as implemented.

## Verification
`tests/test_memory_intelligence.py` verifies inference, procedural, episodic, retrieval and bounded consolidation behavior. Full local regression suite was rerun.
