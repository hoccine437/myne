# learning/curriculum.py
"""Curriculum Engine: build an adaptive learning path from prerequisites.

Design: a curriculum is a sequence of CONCEPTS annotated with prerequisites
and difficulty; known pieces prune themselves; gaps surface; performance on
practice/experiment re-orders the rest in real time. Unfamiliar domains get
a plausible ordering from prerequisite metadata — never a hallucinated fake
syllabus."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class CurriculumUnit:
    concept: str
    prerequisites: tuple = ()
    difficulty: float = 0.5        # 0..1
    status: str = "pending"        # pending | current | mastered | failed


@dataclass
class Curriculum:
    topic: str
    units: list
    curriculum_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    current_index: int = 0

    def to_dict(self):
        return {"topic": self.topic, "units": [u.__dict__ for u in self.units],
                "curriculum_id": self.curriculum_id, "current_index": self.current_index}


class CurriculumEngine:
    def build(self, topic: str, concept_graph: list | None = None,
              already_known: list | None = None) -> Curriculum:
        """concept_graph: [(concept, [prereqs])] or None → minimal starter
        graph (goal, prerequisites detection, application, evaluation)."""
        if concept_graph is None:
            concept_graph = self._default_graph(topic)
        known = set(already_known or [])
        ordered = []
        self._topo(concept_graph, ordered, set())
        units = []
        for concept, prereqs in ordered:
            status = "mastered" if concept in known else ("current" if not units else "pending")
            units.append(CurriculumUnit(concept=concept, prerequisites=tuple(prereqs),
                                        difficulty=self._difficulty(concept_graph, concept),
                                        status=status))
        cur = Curriculum(topic=topic, units=units)
        return cur

    def adapt(self, curriculum: Curriculum, performance: dict) -> Curriculum:
        """performance: {concept: score 0..1} — low score pushes the concept
        forward one slot to be seen earlier, previous unit fills the gap."""
        if not performance:
            return curriculum
        order = sorted(
            range(len(curriculum.units)),
            key=lambda i: (performance.get(curriculum.units[i].concept, 0.5), i))
        ordered_units = sorted(curriculum.units,
                               key=lambda u: (performance.get(u.concept, 0.5),
                                              curriculum.units.index(u)))
        curriculum.units = ordered_units
        return curriculum

    def gaps(self, curriculum: Curriculum) -> list[str]:
        return [u.concept for u in curriculum.units if u.status != "mastered"]

    def mastery_score(self, curriculum: Curriculum) -> float:
        if not curriculum.units:
            return 0.0
        mastered = sum(1 for u in curriculum.units if u.status == "mastered")
        return round(mastered / len(curriculum.units), 2)

    # ------------------------------------------------------------------
    # internals

    def _default_graph(self, topic: str) -> list:
        return [(f"{topic}: identification", []),
                (f"{topic}: vocabulary", [f"{topic}: identification"]),
                (f"{topic}: core operation", [f"{topic}: vocabulary"]),
                (f"{topic}: application", [f"{topic}: core operation"]),
                (f"{topic}: edge cases", [f"{topic}: application"]),]

    def _topo(self, graph, out, seen):
        for node, prereqs in graph:
            if node in seen:
                continue
            for p in prereqs:
                if p in seen:
                    continue
                sub = [x for x in graph if x[0] == p]
                if sub:
                    self._topo(sub, out, seen)
            seen.add(node)
            out.append((node, prereqs))

    def _difficulty(self, graph, concept) -> float:
        deps = [p for n, ps in graph for p in ps if n == concept]
        return round(min(.9, .25 + .12 * len(deps)), 2)
