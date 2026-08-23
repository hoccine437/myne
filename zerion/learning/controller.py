# learning/controller.py
"""LearningController — the one place the self-teaching loop lives.

    TARGET → ASSESS → GAPS → CURRICULUM → ACQUIRE → PRACTICE →
    FEEDBACK → VERIFY → GENERALIZE → STORE → REVIEW → MEASURE

All steps use the existing canonical systems (knowledge manager, runtime
intelligence, critics, agents, tools). Bounded, measurable, auditable:
No runaway loops (bounded iterations), no modifying code (self-evolution
paths are separate and gated upstream), no unverified storage."""

from __future__ import annotations

import os
import time
import uuid

import config

from learning.acquisition import AcquisitionLayer
from learning.curriculum import CurriculumEngine
from learning.errors import ErrorMemory
from learning.meta import MetaLearner
from learning.practice import PracticeEngine, SKILL_LEVELS
from learning.progress import ProgressModel
from learning.retention import RetentionScheduler
from learning.transfer import TransferEngine
from learning.verification import TruthEngine

from knowledge.manager import KnowledgeManager

_DEFAULT_MAX_ITER = 6


class LearningController:
    def __init__(self):
        self.km = KnowledgeManager()
        self.acquisition = AcquisitionLayer()
        self.curriculum = CurriculumEngine()
        self.practice = PracticeEngine()
        self.errors = ErrorMemory()
        self.verify = TruthEngine()
        self.retention = RetentionScheduler()
        self.transfer = TransferEngine()
        self.meta = MetaLearner()
        self.progress = ProgressModel()

    # ------------------------------------------------------------------
    # provider-backed domain study

    def study_domain(self, topic: str, known_concepts: list | None = None,
                     source_text: str = "", source_url: str = "") -> dict:
        """Acquire a real, topic-specific lesson through the same Gemini
        provider used by chat.

        This stores bounded lesson material and recall checks as UNVERIFIED
        knowledge. It deliberately does not convert one model response into
        mastery; an independent source, executable proof, or explicit quiz
        evidence is still required for promotion.
        """
        from learning.teacher import DomainTeacher

        topic = (topic or "").strip()
        report = {
            "topic": topic, "iterations": [], "errors": [],
            "generalization": None, "mastery": [],
            "knowledge_status": "unverified",
            "learning_scope": "model-assisted-study",
            "evidence_checks": 0, "uncertainties": [],
            "finished_reason": None, "final_level": None,
        }
        if not topic:
            report["finished_reason"] = "missing-topic"
            report["message"] = "A topic is required."
            return report

        # On Android/Termux, a no-key study request can still fetch a bounded
        # public reference summary. Explicit URLs work on every platform;
        # source text remains provenance-labelled and unverified.
        if not source_text:
            try:
                from learning.source import fetch_topic, fetch_url
                material = fetch_url(source_url) if source_url else None
                if material is None and not config.get_gemini_api_key() and \
                        "com.termux" in os.environ.get("PREFIX", ""):
                    material = fetch_topic(topic)
                if material is not None:
                    source_text = material.text
                    source_url = material.url
            except Exception:
                pass

        try:
            lesson = DomainTeacher().generate(
                topic, source_text=source_text, source_url=source_url,
                known_concepts=list(known_concepts or []))
        except Exception as error:
            report["finished_reason"] = (
                "needs-domain-evidence" if "GEMINI_API_KEY" in str(error)
                else "teacher-unavailable")
            report["message"] = (
                f"A topic-specific teacher could not be reached: {error}. "
                "Provide GEMINI_API_KEY or topic evidence/source material; "
                "no topic knowledge was stored or marked as mastered."
            )
            return report

        concepts = lesson["concepts"]
        obj = self.progress.open(
            topic, unknown_concepts=[item["name"] for item in concepts])
        report["uncertainties"] = lesson.get("uncertainties", [])
        for item in concepts:
            content = f"{item['name']}: {item['lesson']}"
            record_id = self.acquisition.acquire(
                content, source=lesson.get("source", "gemini-teacher"),
                domain=topic)
            checks = item.get("checks", [])
            report["iterations"].append({
                "concept": item["name"], "record_id": record_id,
                "checks": len(checks), "correct": None,
                "verdict": "unverified", "confidence": 0.3,
            })

        report["lesson"] = {
            "concepts": concepts,
            "source": lesson.get("source"),
            "source_url": lesson.get("source_url", ""),
        }
        report["finished_reason"] = "studied-unverified"
        report["message"] = (
            f"Generated {len(concepts)} topic-specific lesson(s) for {topic!r}. "
            "Material is stored as UNVERIFIED; run independent recall/evidence "
            "before claiming mastery."
        )
        self.progress._persist(obj, event="study-unverified")
        report["final_level"] = self.progress.level_summary(obj)
        return report

    # ------------------------------------------------------------------
    # the deterministic/callback-driven learning loop

    def learn_domain(self, topic: str, known_concepts: list | None = None,
                     practice_attempt_fn=None, truth_fn=None,
                     system_listener=None, max_iterations: int = _DEFAULT_MAX_ITER) -> dict:
        """Run the bounded evidence-gated learning loop.

        ``practice_attempt_fn(prompt)->answer`` must be a subject-specific
        teacher/exercise adapter. ``truth_fn(prompt)`` is optional for the
        synthetic practice path but, when supplied, is actually called and
        its explicit result controls VERIFIED promotion. Without a
        subject-specific practice callback this method only creates a study
        plan and returns ``needs-domain-evidence``; it never pretends that a
        generic arithmetic exercise taught the requested domain.

        Returns a full report (the final experiment's honest audit trail)."""
        started = time.time()
        run_id = uuid.uuid4().hex[:8]

        obj = self.progress.open(topic, unknown_concepts=None)
        cur = self.curriculum.build(topic, already_known=list(known_concepts or []))
        self._system_emit(system_listener, "curriculum.built", {"units": len(cur.units)})

        # Relationships (mission graph): curriculum edges land in the
        # existing world graph (graph_edges) — prerequisite_of between
        # concepts, part_of between concept and domain. Reused on failure
        # (related-concept lookup) instead of a parallel relation store.
        try:
            from intelligence.world import WorldModel
            _world = WorldModel()
            for _u in cur.units:
                _world.link(f"concept:{_u.concept}", "part_of", f"domain:{topic}", .5)
                for _p in _u.prerequisites:
                    _world.link(f"concept:{_p}", "prerequisite_of",
                                f"concept:{_u.concept}", .7)
        except Exception:
            _world = None

        report = {"run_id": run_id, "topic": topic, "iterations": [],
                  "mastery": [], "errors": [], "generalization": None,
                  "finished_reason": None, "final_level": None,
                  "knowledge_status": "unverified",
                  "learning_scope": "domain-evidence-required",
                  "evidence_checks": 0}

        # The production trigger does not have a domain teacher or a
        # subject-specific exercise callback. The old default silently ran
        # arithmetic (`a + b`) for every topic, so `learn kali linux` could
        # report mastery after passing math while learning nothing about
        # Kali. Refuse that false positive; the synthetic math loop remains
        # available to tests/experiments when an explicit callback is passed.
        if practice_attempt_fn is None:
            report["finished_reason"] = "needs-domain-evidence"
            report["message"] = (
                f"No domain-specific learning evidence was supplied for {topic!r}. "
                "Provide source material or a subject-specific teacher/exercise "
                "before Zerion can claim it learned the topic."
            )
            self.progress._persist(obj, event="needs-domain-evidence")
            report["final_level"] = self.progress.level_summary(obj)
            return report

        iterations = 0
        while iterations < max_iterations:
            iterations += 1
            unit = next((u for u in cur.units if u.status != "mastered"), None)
            if unit is None:
                report["finished_reason"] = "mastery"
                break
            concept = unit.concept
            # acquire+: never store unclassified
            frag = self.acquisition.classify(f"beginning to master {concept} in {topic}",
                                             source="self-study")
            rec_id = self.acquisition.acquire(
                frag.content, source=frag.source, domain=topic)
            self._system_emit(system_listener, "acquired", frag.kind)

            # practice at this unit's difficulty (skill named after concept)
            level = obj.skill_levels.get(concept, "exposed")
            rnd = int(time.time()) + iterations
            ex = self.practice.generate(concept, level, seed=rnd)
            result = self.practice.attempt(ex, attempt_fn=practice_attempt_fn)
            if hasattr(result, 'level'):
                result.level = level
            self.progress.note_practice(obj, result)

            # feedback → verdict on the record + errors. A truth_fn is an
            # actual check, not a truth-shaped flag: invoke it and normalize
            # its result before allowing VERIFIED promotion.
            truth_state = None
            truth_verified = False
            if truth_fn is not None:
                report["evidence_checks"] += 1
                try:
                    truth_state = truth_fn(ex.prompt)
                    truth_verified = self._truth_verified(truth_state)
                except Exception as truth_error:
                    truth_state = {"state": "uncertain", "error": str(truth_error)}
            if isinstance(truth_state, dict):
                state_name = str(truth_state.get("state", "")).lower()
                evidence = (["support", "support"] if state_name == "supported"
                            else ["support"] if truth_verified
                            else ["contradict"] if truth_state is not None else
                            [result.correct and "support" or "contradict"])
            elif truth_state is not None:
                state_name = str(truth_state).lower()
                evidence = (["support", "support"] if state_name == "supported"
                            else ["support"] if truth_verified
                            else ["contradict"])
            else:
                evidence = [result.correct and "support" or "contradict"]
            verdict = self.verify.evaluate(rec_id, evidence,
                                           executable_proof=truth_verified)
            obj.confidence = verdict["confidence"]
            self.progress.note_verdict(obj, verdict["state"])

            # A practice answer can advance the local skill model. If a
            # teacher/proof callback was supplied, its verdict must agree;
            # otherwise a correct-looking answer is not topic mastery.
            practice_pass = result.correct and (
                truth_fn is None or verdict["state"] in ("supported", "verified")
            )
            if practice_pass:
                # promote: level up one slot only after the exercise evidence
                # (and any supplied truth evidence) passes.
                idx = SKILL_LEVELS.index(level)
                new_level = SKILL_LEVELS[min(idx + 1, len(SKILL_LEVELS) - 1)]
                self.progress.note_skill(obj, concept, new_level)
                unit.status = "mastered"
                self.progress.mark_known(obj, concept)
                self.retention.note_pass(rec_id)
            else:
                cmd, hint = self._cause_and_fix(ex, result)
                # record under the CONCEPT as well as the literal exercise —
                # error memory is retrieved by "similar task", and the task
                # future-me will recognize is the subject, not the operands
                error_id = self.errors.record(
                    f"{concept} — exercise: {ex.prompt}",
                    str(result.actual), str(ex.expected),
                    cmd, hint, solution="")
                report["errors"].append({"concept": concept,
                                         "exercise": ex.prompt,
                                         "record_id": error_id,
                                         "feedback": result.feedback})
                self.progress.note_error(obj, result.feedback)
                # backoff: review this failure soon
                self.retention.note_fail(rec_id)
                self._system_emit(system_listener, "practice.failed", result.feedback)
                # relationship lookup: prerequisites of the failed concept may
                # be the real gap — surface what the graph knows, honestly
                related = []
                if _world is not None:
                    try:
                        related = [r["source"] for r in _world.related(f"concept:{concept}")
                                   if r["relation"] == "prerequisite_of"]
                    except Exception:
                        related = []
                if related:
                    report.setdefault("related_gaps", []).extend(related)
                if iterations >= 2 and not unit.prerequisites and not related:
                    # can't recover without external info — report limitation honestly
                    report["finished_reason"] = "stuck-no-new-evidence"
                    break

            report["iterations"].append({"concept": concept, "level": level,
                                         "correct": result.correct,
                                         "verdict": verdict["state"],
                                         "confidence": verdict["confidence"]})
            report["mastery"].append(self.curriculum.mastery_score(cur))

        # generalization probe on NEW generated seeds (no shared seed = honest)
        # NOTE: salted with run_id — bare int(time.time()) replays the exact
        # same "unseen" probes for two runs sharing a second, which would let
        # a subject pass by recall instead of generalization.
        gen_seed = (int(time.time()) + int(run_id, 16)) % 100000
        probes = []
        for _ in range(3):
            ex = self.practice.generate(topic + ": generalized probe", "competent",
                                        seed=(gen_seed := gen_seed + 137))
            probes.append(ex)
        passes = 0
        for ex in probes:
            pr = self.practice.attempt(ex, attempt_fn=practice_attempt_fn)
            ok = pr.correct
            passes += ok
            self.progress.note_generalization(obj, ok)
        gen_score = round(passes / len(probes), 2)
        report["generalization"] = {"probes": len(probes), "passes": passes,
                                    "score": gen_score}
        obj.generalization_passes += passes
        obj.generalization_fails += len(probes) - passes
        report["mastery"].append(self.curriculum.mastery_score(cur))

        # meta-learning: this run's strategy (acquisition→practice→verify) outcome
        elapsed = time.time() - started
        strategy = "acquire+practice+verify+review"
        retention_passes = obj.generalization_passes
        retention_fails = obj.generalization_fails
        self.meta.note_strategy(strategy, elapsed, retention_passes, retention_fails)
        self.progress._persist(obj, event="loop-complete")

        report["final_level"] = self.progress.level_summary(obj)
        report["final_level"]["strategy"] = strategy
        report["final_level"]["elapsed_s"] = round(elapsed, 2)
        if not report.get("finished_reason"):
            report["finished_reason"] = ("budget-complete" if iterations >= max_iterations
                                         else "mastery")
        return report

    # ------------------------------------------------------------------
    # internals

    @staticmethod
    def _truth_verified(value) -> bool:
        """Normalize a teacher/proof result without treating mere callback
        presence as evidence. Only explicit verified/proof signals promote a
        record; everything else remains uncertain or supported."""
        if isinstance(value, dict):
            state = str(value.get("state", "")).lower()
            return state == "verified" or value.get("verified") is True or \
                value.get("executable_proof") is True
        return value is True

    def _cause_and_fix(self, ex, result) -> tuple[str, str]:
        """Cause classification from observable structure, nothing assumed."""
        prompt = ex.prompt or ""
        try:
            if isinstance(result.expected, (int, float)) and isinstance(result.actual, (int, float)):
                if result.actual > result.expected * 5: return "ordering", "carry place error"
                if abs(result.actual - result.expected) <= 2: return "boundary", "off by small amount"
                return "arithmetic", "recompute precisely"
        except Exception:
            pass
        return "unknown", "ask the user for the missing rule or evidence"

    def _system_emit(self, listener, event: str, payload=None) -> None:
        if callable(listener):
            listener({"event": event, "payload": payload, "ts": time.time()})


def _system_listen(listener, event, payload) -> bool:
    return callable(listener)
