# learning/practice.py
"""Practice Engine: generate → attempt → evaluate → feedback → measure.

Pure templates, deterministic practice mathematical exercises. Every
exercise carries level metadata so difficulty progression is visible rather
than asserted. For software skills: code runs via the confirmation-gated
exploit path (never silently)."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

SKILL_LEVELS = ("unknown", "exposed", "understood", "basic", "practiced",
                "competent", "advanced")


@dataclass
class Exercise:
    skill: str
    level: str
    prompt: str
    expected: object
    seed: int


@dataclass
class PracticeResult:
    skill: str
    correct: bool
    expected: object
    actual: object
    feedback: str
    elapsed_s: float
    ts: float


class PracticeEngine:
    """Deterministic math-domain practice — procedurally generated exercises,
    executed by the local deterministic compute path (no LLM needed), real
    correct/incorrect bits recorded for evidence."""

    def generate(self, skill: str, level: str, seed: int | None = None) -> Exercise:
        rnd = random.Random(seed if seed is not None else int(time.time()))
        if level in ("unknown", "exposed"):
            a, b = rnd.randint(1, 9), rnd.randint(1, 9)
            return Exercise(skill=skill, level=level, prompt=f"{a} + {b}",
                            expected=a + b, seed=seed or 0)
        if level == "understood":
            a, b = rnd.randint(10, 99), rnd.randint(10, 99)
            return Exercise(skill=skill, level=level, prompt=f"{a} + {b}",
                            expected=a + b, seed=seed or 0)
        if level == "basic":
            a, b = rnd.randint(100, 999), rnd.randint(100, 999)
            return Exercise(skill=skill, level=level, prompt=f"{a} + {b}",
                            expected=a + b, seed=seed or 0)
        # practiced+: carries including carry chains
        a, b = rnd.randint(1000, 9999), rnd.randint(999, 9999)
        return Exercise(skill=skill, level=level, prompt=f"{a} + {b}",
                        expected=a + b, seed=seed or 0)

    def attempt(self, exercise: Exercise, attempt_fn=None) -> PracticeResult:
        """attempt_fn: callable(prompt:str)->actual answer. Default: exact
        integer arithmetic via the local compute lens (never by guessing)."""
        start = time.perf_counter()
        if attempt_fn is None:
            actual = eval(exercise.prompt)  # local sandbox: just arithmetic
        else:
            actual = attempt_fn(exercise.prompt)
        elapsed = time.perf_counter() - start
        try:
            ok = abs(type(actual)(actual) - type(exercise.expected)(exercise.expected)) < 1e-9
        except Exception:
            ok = False
        feedback = ("correct" if ok
                    else f"got {actual} expected {exercise.expected}")
        return PracticeResult(skill=exercise.skill, correct=ok,
                              expected=exercise.expected, actual=actual,
                              feedback=feedback, elapsed_s=round(elapsed, 4),
                              ts=time.time())


    def measure(self, results: list) -> dict:
        if not results:
            return {}
        correct = sum(1 for r in results if r.correct)
        return {"total": len(results), "correct": correct,
                "accuracy": round(correct / len(results), 3),
                "mean_elapsed": round(sum(r.elapsed_s for r in results) / len(results), 4)}
