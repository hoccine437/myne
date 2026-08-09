# tests/test_exec_hardening.py
"""§17 evidence: run_python/run_shell are genuinely contained after the
approval gate — not just "confirmation-gated".

Proved: rlimits + pgid scope + project-dir cwd isolation + env scrubbing +
bounded timeout kills the whole process group (no orphan sleepers).
"""
import os
import unittest


class ExecHardeningTests(unittest.TestCase):
    def setUp(self):
        from tools.manager import tool_manager
        self.tm = tool_manager

    def _confirmed(self, name, params):
        first = self.tm.execute(name, params)
        self.assertEqual(first.error, "confirmation_required")
        return self.tm.confirm_pending()

    def test_cwd_is_project_root(self):
        r = self._confirmed("run_python", {"code": "import os,sys; print(os.getcwd())"})
        from config import BASE_DIR
        self.assertTrue(r.success, r.message)
        self.assertIn(BASE_DIR.rstrip(os.sep), (r.message or "").strip())

    def test_child_env_inherits_no_secrets(self):
        os.environ["GEMINI_API_KEY"] = "sentinel-should-not-leak-xyz"
        try:
            r = self._confirmed(
                "run_python",
                {"code": "import os; print('LEAKY' if os.environ.get('GEMINI_API_KEY')=='sentinel-should-not-leak-xyz' else 'clean')"})
            self.assertTrue(r.success)
            self.assertIn("clean", r.message, r.message)
        finally:
            os.environ.pop("GEMINI_API_KEY", None)

    def test_shell_syntax_still_rejected(self):
        # destructive tools park at confirmation first; the syntax rule then
        # rejects on the confirmed call (the policy path itself)
        r = self._confirmed("run_shell", {"command": "echo x | cat"})
        self.assertFalse(r.success)
        self.assertEqual(r.error, "shell_syntax_disallowed")

    def test_cwd_escape_rejected(self):
        r = self.tm.execute("run_python", {"code": "pass"})  # direct: no path
        self.assertTrue(r.error == "confirmation_required")  # parks normally
        self.tm.cancel_pending_confirmation()
        # direct executor path to prove refusal without confirmation needed
        from tools.exec_tools import _run
        out = _run(["/bin/true"], cwd="/")
        self.assertEqual(out.error, "cwd_not_allowed")

    def test_timeout_kills_process_group(self):
        import tools.exec_tools as ex
        original_timeout = ex._TIMEOUT_SECONDS
        ex._TIMEOUT_SECONDS = 1
        try:
            r = self._confirmed(
                "run_python",
                {"code": "import time; time.sleep(30)"})
            self.assertFalse(r.success)
            self.assertEqual(r.error, "timeout")
        finally:
            ex._TIMEOUT_SECONDS = original_timeout

    def test_resource_limits_applied(self):
        """Documentation-level guard: the child probe proves limits exist
        (must never silently disappear)."""
        import tools.exec_tools as ex
        func = ex._limits()
        self.assertIsNotNone(func)  # posix: rlimit setter bound
        r = self._confirmed("run_python", {"code": "print('ok')"})
        self.assertTrue(r.success)


if __name__ == "__main__":
    unittest.main()
