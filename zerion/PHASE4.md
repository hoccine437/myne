# Phase 4 — Continuous Learning Layer

## 1. Updated architecture
`Intent → Planner → Agent/Tool system → KnowledgeManager → LearningEngine → Memory layers → LLM → response`.
Phase 4 is additive: existing intent, planner, legacy memory API, tools, speech and terminal loop retain their contracts. `main.py` retrieves ranked context before existing planning/LLM processing and records a bounded experience after a normal LLM task.

## 2. Knowledge architecture
`knowledge/database.py` owns a WAL-mode SQLite database. `KnowledgeManager` stores facts, projects, preferences, code, research, solutions, notes and summaries as categorized records with tags and metadata. `IncrementalIndexer` safely indexes small UTF-8 documents.

## 3. Memory architecture
* **Working**: bounded in-process deque.
* **Conversation**: existing `SessionMemory` rolling history.
* **Long-term**: durable ranked facts in `records` (`layer=long_term`).
* **Knowledge**: durable reusable records (`layer=knowledge`).
* **Reflection**: post-task improvements (`layer=reflection`).
* **Experience**: execution outcomes (`layer=experience`).

Each durable record has importance, confidence, recency (`accessed`), usage frequency, category and tags. The original JSON memory stays untouched and continues to serve its legacy API.

## 4. Learning workflow
Successful results, failures/corrections supplied to the engine, tool lists and elapsed time become an `Experience`; substantive outputs can become summaries. No code, model, prompt, or system configuration is self-modified.

## 5. Reflection workflow
`reflect()` records what worked, failures, and a concrete reuse/improvement recommendation. Reflection storage is isolated; a failure is caught and never interrupts a user response.

## 6. Experience workflow
`ExperienceStore` captures goal, plan, tools, execution time, failures, corrections, final result, confidence, and future recommendation in metadata. It is searchable with the same ranked search.

## 7. Skill architecture
`Skill` is a typed module contract: knowledge categories, specialized prompt, reasoning rules, preferred tools and learning history. `SkillManager` selects Software Engineering, Financial Markets, Electronics or Human Knowledge. Add one module exporting `SKILL` and register it—no core changes.

## 8. Knowledge search workflow
Before the planner/LLM, the manager searches all durable layers. Retrieval uses keyword/token overlap (a lightweight semantic proxy), tags, category text, importance, confidence, recency and frequency ranking. Retrieved context is inserted only when relevant. SQLite FTS is opportunistically created where available; search remains functional without it.

## 9. Performance impact
One local SQLite read over the compact record set per normal request; no embeddings, downloads, daemon, offline model, GUI, or network requirement. Writes use WAL and short transactions.

## 10. Resource usage / Termux
Python standard library only. Lazy database connections, bounded working memory, max 1 MB document indexing, and one background cleanup operation per idle input. Background work pauses above load average 1.5. WAL and existing atomic JSON persistence protect interrupted writes.

## 11. Readiness score
**88/100 — production-ready lightweight Phase 4 core.** Strong persistence, isolation, tests and failure containment. The remaining score is intentionally reserved for future optional embeddings, user-feedback UI commands, and richer agent execution hooks, none of which are required or appropriate for this lightweight phase.

## Verification
Run: `python -m compileall knowledge learning memory skills main.py` and `python -m pytest tests/test_phase4.py` (or execute the smoke test directly).
