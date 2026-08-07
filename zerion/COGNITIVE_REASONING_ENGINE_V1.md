# Cognitive Reasoning Engine v1

## Architecture
`CognitiveReasoningEngine` is an additive module in `cognition/reasoning.py`. It is invoked by `main.py` after capability retrieval and before existing intent/planner/LLM routing. It reuses capability records, the knowledge database, Constitution, Runtime Intelligence, Reflection and Experience paths; it does not execute tools or create a second memory store.

## Pipeline
1. Receive goal and retrieved capability records.
2. Use records as evidence.
3. Generate bounded reusable hypotheses and a strategy.
4. Estimate confidence from available evidence.
5. Store only revisable inference records in the existing knowledge database (`layer=inference`).
6. Add strategy/confidence/hypotheses to the existing LLM context.
7. Existing Constitution, planner, approval, runtime reflection and learning paths continue unchanged.

## Inference lifecycle
An inference contains statement, confidence, evidence, reasoning chain, timestamp and `hypothesis` status. It is not treated as a verified fact. Existing future knowledge/evidence can supersede or outweigh it; the engine does not overwrite verified knowledge.

## Constitutional reasoning
The Constitution now includes `REA-001` (revisable inference), `REA-002` (evidence and uncertainty), and `REA-003` (simple reliable reasoning). Constitution hash and protected-core locks were regenerated after owner-authorized protected content changes.

## Personality model
`prompt.txt` now defines a stable Zerion software identity: transparent, calm, evidence-driven, uncertainty-aware, privacy-respecting, and non-human. It preserves the existing JSON response contract.

## Limitations
This is transparent software reasoning, not consciousness, sentience, human cognition, autonomous research, or automatic action. Confidence is a bounded heuristic and not evidence by itself. Live provider behavior remains separate from local reasoning tests.

## Verification
`tests/test_reasoning.py` verifies pipeline output, hypothesis status, confidence bounds, constitutional reasoning law parsing and personality prompt loading. Main startup and the full local regression suite were rerun.
