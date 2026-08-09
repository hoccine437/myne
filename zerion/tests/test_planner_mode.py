# tests/test_planner_mode.py
"""§9 automatic planner escalation + §12 observation gates."""
import json
import unittest

import config
from planner.executor import execute_plan
from planner.models import Plan, Task


class PlannerModeTests(unittest.TestCase):
    def setUp(self):
        self._mode = config.PLANNER_MODE
        self._enabled = config.PLANNER_ENABLED

    def tearDown(self):
        config.PLANNER_MODE = self._mode
        config.PLANNER_ENABLED = self._enabled

    def test_auto_escalates_complex_only(self):
        config.PLANNER_MODE = "auto"
        config.PLANNER_ENABLED = False
        self.assertTrue(config.planner_active(True))
        self.assertFalse(config.planner_active(False))

    def test_on_always(self):
        config.PLANNER_MODE = "on"
        config.PLANNER_ENABLED = False
        self.assertTrue(config.planner_active(False))
        self.assertTrue(config.planner_active(True))

    def test_off_never(self):
        config.PLANNER_MODE = "off"
        config.PLANNER_ENABLED = True   # explicit mode wins over toggle
        self.assertFalse(config.planner_active(True))

    def test_legacy_toggle_preserved(self):
        # exact legacy contract: PLANNER_ENABLED=true + needs_planning=True
        config.PLANNER_MODE = "auto"
        config.PLANNER_ENABLED = True
        self.assertTrue(config.planner_active(True))
        self.assertFalse(config.planner_active(False))  # trivial stays free


class ExpectationVerificationTests(unittest.TestCase):
    def test_success_without_expected_evidence_fails(self):
        task = Task(id=1, description="must compute", tool_name="calculate",
                    parameters={"expression": "6*7"}, expected_result="999",
                    depends_on=[])
        summary = execute_plan(Plan(goal="t", tasks=[task]))
        self.assertFalse(summary["all_succeeded"], "contradicting output must not count as success")
        self.assertEqual(summary["tasks"][0]["state"], "failed")

    def test_expected_evidence_present_passes(self):
        task = Task(id=1, description="compute", tool_name="calculate",
                    parameters={"expression": "6*7"}, expected_result="42")
        summary = execute_plan(Plan(goal="t", tasks=[task]))
        self.assertTrue(summary["all_succeeded"])

    def test_no_expectation_unchanged(self):
        task = Task(id=1, description="compute", tool_name="calculate",
                    parameters={"expression": "1+1"})
        summary = execute_plan(Plan(goal="t", tasks=[task]))
        self.assertTrue(summary["all_succeeded"])


if __name__ == "__main__":
    unittest.main()
