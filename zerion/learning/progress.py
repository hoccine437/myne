# learning/progress.py
"""Learning Progress Model — multiple evidence dimensions, never one number.

A LearningObjective records: topic, prerequisites, known/unknown concepts,
skill levels, confidence-and-evidence pairs, practice history, error
history, verification verdict counts, generalization probes.
Growth on every dimension is stored."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict

from knowledge.manager import KnowledgeManager


@dataclass
class LearningObjective:
    topic: str
    prerequisites: tuple = ()
    known_concepts: list = field(default_factory=list)
    unknown_concepts: list = field(default_factory=list)
    skill_levels: dict = field(default_factory=dict)   # {skill: level}
    confidence: float = 0.0
    evidence: list = field(default_factory=list)
    practice_history: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    verify_passes: int = 0
    verify_fails: int = 0
    generalization_passes: int = 0
    generalization_fails: int = 0
    last_reviewed: float = 0.0
    objective_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def to_dict(self) -> dict:
        return asdict(self)


class ProgressModel:
    def __init__(self):
        self.km = KnowledgeManager()

    def open(self, topic: str, prerequisites: tuple = (),
             unknown_concepts: list | None = None) -> LearningObjective:
        obj = LearningObjective(topic=topic, prerequisites=prerequisites,
                                unknown_concepts=list(unknown_concepts or []),
                                last_reviewed=time.time())
        self._persist(obj, event="opened")
        return obj

    def mark_known(self, obj: LearningObjective, concept: str) -> None:
        if concept in obj.unknown_concepts:
            obj.unknown_concepts.remove(concept)
        if concept not in obj.known_concepts:
            obj.known_concepts.append(concept)
        self._persist(obj, event="known")

    def note_skill(self, obj: LearningObjective, skill: str, level: str) -> None:
        obj.skill_levels[skill] = level
        self._persist(obj, event="skill")

    def note_practice(self, obj: LearningObjective, result) -> None:
        obj.practice_history.append({
            "correct": result.correct, "level": result.level if hasattr(result, "level") else "?",
            "ts": time.time()})
        self._persist(obj, event="practice")

    def note_error(self, obj: LearningObjective, failure: str) -> None:
        obj.errors.append({"failure": failure[:200], "ts": time.time()})
        self._persist(obj, event="error")

    def note_verdict(self, obj: LearningObjective, state: str) -> None:
        if state == "verified":
            obj.verify_passes += 1
        elif state in ("contradicted", "rejected", "uncertain"):
            obj.verify_fails += 1
        obj.last_reviewed = time.time()
        self._persist(obj, event="verdict")

    def note_generalization(self, obj: LearningObjective, ok: bool,
                            note: str = "") -> None:
        if ok:
            obj.generalization_passes += 1
        else:
            obj.generalization_fails += 1
        obj.last_reviewed = time.time()
        self._persist(obj, event="generalization")

    def level_summary(self, obj: LearningObjective) -> dict:
        # learning is multi-dimensional — the honest composite needs several axes
        mastery = round(len(obj.known_concepts) /
                        max(1, len(obj.known_concepts) + len(obj.unknown_concepts)), 2)
        gen = (obj.generalization_passes /
               max(1, obj.generalization_passes + obj.generalization_fails))
        verify = obj.verify_passes / max(1, obj.verify_passes + obj.verify_fails)
        return {"topic": obj.topic, "mastery": mastery,
                "generalization_rate": round(gen, 2), "verify_rate": round(verify, 2),
                "skill_levels": obj.skill_levels, "errors": len(obj.errors),
                "confidence": obj.confidence}

    def _persist(self, obj: LearningObjective, event: str) -> None:
        self.km.store(
            content=f"learning objective: {obj.topic} ({event})",
            category="learning_progress", tags=[obj.topic, event],
            importance=.55, confidence=.9,
            metadata={"objective": obj.to_dict(), "event": event,
                      "ts": time.time()},
            layer="learning_progress")
