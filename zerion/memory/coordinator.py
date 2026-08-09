# memory/coordinator.py
"""Memory Coordinator — ONE policy layer deciding where knowledge is stored.

This is a coordination policy, NOT a new store. The stores stay:
  - memory/memory_manager.py JSON file → persona facts (identity/prefs/etc.)
  - knowledge/zerion_knowledge.db      → operational records (experiences,
    capabilities, learning, telemetry, comm patterns)
  - SessionMemory (in-process)         → rolling conversation turns

What the coordinator centralizes (callers must not pick a raw store when
one of these routes answers):
  store(kind, content, **meta):   writes go here; routes by policy
  consolidate():                  delegates to the existing MemoryOptimizer
  status():                       read-only census (JSON sections + DB rows)

NOT duplicated here on purpose: prompt-time context assembly stays in
main.minimal_memory_for_prompt + knowledge.retrieve_context (read paths
already bounded; re-implementing them would fork the prompt contract).
"""

from __future__ import annotations

_PERSONA_PREFIX = "memory.persona."   # e.g. "memory.persona.identity.name"


class MemoryCoordinator:
    def store(self, kind: str, content: str, **meta) -> str:
        """Route a write by kind. Returns the store used (for audit lines)."""
        if kind.startswith(_PERSONA_PREFIX):
            from memory.memory_manager import update_memory
            path = kind[len(_PERSONA_PREFIX):].split(".")
            if len(path) != 2 or not all(path):
                raise ValueError(f"persona kind must be 'section.key', got {kind!r}")
            update_memory({path[0]: {path[1]: {"value": content}}})
            return "json-memory"
        from knowledge.manager import KnowledgeManager
        KnowledgeManager().store(
            content, category=str(meta.get("category", "coordinator")),
            tags=list(meta.get("tags", [])),
            importance=float(meta.get("importance", .5)),
            confidence=float(meta.get("confidence", .6)),
            metadata=dict(meta.get("metadata") or {}),
            layer=str(meta.get("layer", "knowledge")))
        return "knowledge-db"

    def consolidate(self) -> str:
        from learning.optimizer import MemoryOptimizer
        return f"coordinator consolidate: removed {MemoryOptimizer().consolidate()} empty records"

    def status(self) -> dict:
        out = {"json_sections": {}, "knowledge_records": None}
        try:
            from memory.memory_manager import load_memory
            mem = load_memory()
            out["json_sections"] = {k: len(v or {}) for k, v in mem.items()}
        except Exception as e:
            out["json_error"] = str(e)
        try:
            from knowledge.manager import KnowledgeManager
            out["knowledge_records"] = KnowledgeManager().db.query(
                "SELECT COUNT(*) AS n FROM records")[0]["n"]
        except Exception as e:
            out["knowledge_error"] = str(e)
        return out


coordinator = MemoryCoordinator()
