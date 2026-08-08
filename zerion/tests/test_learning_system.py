# tests/test_learning_system.py
"""Universal-learning battery: acquisition, truth engine, curriculum,
practice, error memory, retention, transfer, meta-learning, progress,
tools, and the final experiment.

The experiment is a synthetic arithmetic domain ('dot-7' base-7 addition) —
its teacher is real executed arithmetic, its exercises are generated, its
failures/corrections are measured, its generalization probe uses unseen
seeds. No judgment is inflated by a self-claim."""
import os
import sys
import tempfile
import unittest
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)


def isolate_db():
    tmp = tempfile.TemporaryDirectory()
    import knowledge.database as kdb
    orig = kdb.Database.__init__.__defaults__
    kdb.Database.__init__.__defaults__ = (os.path.join(tmp.name, "k.db"),)
    return tmp, orig


class AcquisitionTests(unittest.TestCase):
    def test_classification_markers(self):
        from learning.acquisition import AcquisitionLayer
        a = AcquisitionLayer()
        self.assertEqual(a.classify("claims that X", source="document").kind, "claim")
        self.assertEqual(a.classify("benchmark shows it", source="experiment").kind,
                         "fact")
        self.assertEqual(a.classify("it probably does", source="user").kind, "hypothesis")
        self.assertEqual(a.classify("nothing observed", source="experiment").kind, "unknown")

    def test_acquire_holds_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            import knowledge.database as kdb
            orig = kdb.Database.__init__.__defaults__
            kdb.Database.__init__.__defaults__ = (os.path.join(tmp, "k.db"),)
            try:
                from learning.acquisition import AcquisitionLayer
                from knowledge.manager import KnowledgeManager
                rid = AcquisitionLayer().acquire("X claims Y", source="document",
                                                 domain="law")
                row = KnowledgeManager().db.query(
                    "SELECT metadata, category FROM records WHERE id=?", (rid,))[0]
                import json as _json
                meta = _json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                self.assertEqual(row["category"], "frag:claim")
                self.assertEqual(meta["verification_status"], "unverified")
                self.assertEqual(meta["fragment_kind"], "claim")
            finally:
                    kdb.Database.__init__.__defaults__ = orig


class TruthEngineTests(unittest.TestCase):
    def test_promotion_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            import knowledge.database as kdb
            orig = kdb.Database.__init__.__defaults__
            kdb.Database.__init__.__defaults__ = (os.path.join(tmp, "k.db"),)
            try:
                from learning.acquisition import AcquisitionLayer
                from learning.verification import TruthEngine
                te = TruthEngine()
                rid = AcquisitionLayer().acquire("twelve times two is twenty-four", source="user")
                out = te.evaluate(rid, ["support", "support"])
                self.assertEqual(out["state"], "supported")
                out = te.evaluate(rid, ["contradict", "support"], executable_proof=True)
                # executable proof wins
                self.assertEqual(out["state"], "verified")
            finally:
                kdb.Database.__init__.__defaults__ = orig


class CurriculumTests(unittest.TestCase):
    def test_build_and_prune(self):
        from learning.curriculum import CurriculumEngine
        e = CurriculumEngine()
        cur = e.build("robotics", already_known=[])
        concepts = [u.concept for u in cur.units]
        self.assertEqual(concepts[0], "robotics: identification")
        self.assertEqual(e.mastery_score(cur), 0)

    def test_adapt_raises_failures(self):
        from learning.curriculum import CurriculumEngine
        e = CurriculumEngine()
        cur = e.build("robotics")
        cur.units[0].status = "mastered"
        cur = e.adapt(cur, {"robotics: vocabulary": 0.1})
        self.assertNotEqual(cur.units[0].concept, "robotics: identification")


class PracticeTests(unittest.TestCase):
    def test_generated_levels_get_harder(self):
        from learning.practice import PracticeEngine
        p = PracticeEngine()
        easy = p.generate("arithmetic", "exposed", seed=1)
        hard = p.generate("arithmetic", "competent", seed=2)
        x = easy.prompt.split("+")
        self.assertEqual(int(x[0]) + int(x[1]), easy.expected)
        self.assertIn("+", hard.prompt)

    def test_attempt_marks_wrong(self):
        from learning.practice import PracticeEngine
        p = PracticeEngine()
        ex = p.generate("arithmetic", "exposed", seed=3)
        r = p.attempt(ex, attempt_fn=lambda pr: ex.expected + 1)
        self.assertFalse(r.correct)
        self.assertEqual(r.actual, ex.expected + 1)


class ErrorMemoryTests(unittest.TestCase):
    def test_error_record_retrievable(self):
        tmp, orig = isolate_db()
        try:
            from learning.errors import ErrorMemory
            em = ErrorMemory()
            rid = em.record("carry add", "sum 12", "wrong binary carry",
                           "arithmetic", "two-step carry", "right summary method")
            hits = em.retrieve_similar("carry addition", limit=5)
            self.assertTrue(hits)
            self.assertEqual(hits[0]["cause"], "arithmetic")
        finally:
            tmp.cleanup()
            self._restore(orig)

    def _restore(self, orig):
        import knowledge.database as kdb
        kdb.Database.__init__.__defaults__ = orig


class RetentionTests(unittest.TestCase):
    def _meta(self, rid):
        from knowledge.manager import KnowledgeManager
        import json as _json
        row = KnowledgeManager().db.query("SELECT metadata FROM records WHERE id=?", (rid,))[0]
        return _json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]

    def test_interval_doubles_and_halves(self):
        tmp, orig = isolate_db()
        try:
            from learning.retention import RetentionScheduler
            from knowledge.manager import KnowledgeManager
            rid = KnowledgeManager().store("due me", "note", ["rev"], .5, .8,
                                           {"review_interval_days": 1.0},
                                           layer="knowledge")
            rs = RetentionScheduler()
            rs.note_pass(rid)
            meta = self._meta(rid)
            self.assertGreater(meta["review_interval_days"], 1.0)
            rs.note_fail(rid)
            meta2 = self._meta(rid)
            self.assertLess(meta2["review_interval_days"], meta["review_interval_days"])
        finally:
            tmp.cleanup()
            self._restore(orig)
    def _restore(self, orig):
        import knowledge.database as kdb
        kdb.Database.__init__.__defaults__ = orig


class MetaLearningTests(unittest.TestCase):
    def test_best_strategy_dominance(self):
        tmp, orig = isolate_db()
        try:
            from learning.meta import MetaLearner
            from knowledge.manager import KnowledgeManager
            m = MetaLearner()
            m.note_strategy("spaced", 2.0, retention_passes=8, retention_fails=1)
            m.note_strategy("massed", 1.0, retention_passes=1, retention_fails=4)
            out = MetaLearner().best_strategy(1)
            self.assertEqual(out[0]["strategy"], "spaced")
        finally:
            tmp.cleanup()
            self._restore(orig)

    def _restore(self, orig):
        import knowledge.database as kdb
        kdb.Database.__init__.__defaults__ = orig


class ProgressTests(unittest.TestCase):
    def test_multi_dimensional_level(self):
        tmp, orig = isolate_db()
        try:
            from learning.progress import ProgressModel, LearningObjective
            pm = ProgressModel()
            obj = pm.open("compiler theory")
            pm.mark_known(obj, "lexing")
            pm.note_skill(obj, "lexing", "understood")
            pm.note_verdict(obj, "verified")
            pm.note_generalization(obj, True)
            s = pm.level_summary(obj)
            self.assertEqual(s["mastery"], 1.0)
            self.assertEqual(s["verify_rate"], 1.0)
            self.assertEqual(obj.skill_levels["lexing"], "understood")
        finally:
            tmp.cleanup()
            self._restore(orig)

    def _restore(self, orig):
        import knowledge.database as kdb
        kdb.Database.__init__.__defaults__ = orig


class FinalExperimentTests(unittest.TestCase):
    def test_self_teaching_loop_end_to_end(self):
        from tests.demo_self_teaching import run
        report = run()
        exp = report["experiment"]
        self.assertEqual(exp["finished_reason"], "mastery")
        self.assertTrue(exp["corrected_strategy_accuracy"].startswith("3/3"))
        self.assertEqual(report["generalization"]["score"], 1.0)

    def test_tool_surface(self):
        from tools.manager import tool_manager
        self.assertIsNotNone(tool_manager.get_tool("learn_domain"))
        self.assertIsNotNone(tool_manager.get_tool("learn_progress"))
        self.assertIsNotNone(tool_manager.get_tool("review_due"))


if __name__ == "__main__":
    unittest.main()
