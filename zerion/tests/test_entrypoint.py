# tests/test_entrypoint.py
"""Official entry-point contract: `python main.py` boots the Web UI by
default; `--terminal` runs the minimal built-in REPL; `--help` documents;
UI-less hosts degrade honestly.
"""

import os
import signal
import socket
import subprocess
import sys
import time
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class EntrypointTests(unittest.TestCase):
    def test_default_boots_ui(self):
        port = free_port()
        env = os.environ.copy()
        env["ZERION_UI_NO_AUTOOPEN"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "main.py", "--port", str(port)],
            cwd=BASE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True)
        try:
            import urllib.request
            deadline = time.time() + 20
            body = b""
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.5) as r:
                        body = r.read()
                        break
                except Exception:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.25)
            self.assertIn(b"ZERION", body, "default main.py must serve the UI")
        finally:
            proc.send_signal(signal.SIGTERM)
            out, _ = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 0, out[-400:])
        self.assertNotIn("Traceback", out)

    def test_terminal_flag_runs_repl(self):
        proc = subprocess.run(
            [sys.executable, "main.py", "--terminal"],
            input="/help\nexit\n", capture_output=True, text=True,
            cwd=BASE, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr[-200:])
        self.assertIn("Commands:", proc.stdout)
        self.assertNotIn("Traceback", proc.stdout)
        self.assertIn("Zerion is online and ready", proc.stdout.replace("[INFO]", ""))

    def test_help_lists_modes(self):
        proc = subprocess.run([sys.executable, "main.py", "--help"],
                              capture_output=True, text=True, cwd=BASE, timeout=15)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--terminal", proc.stdout)

    def test_run_loop_still_importable_and_deduplicated(self):
        # main.run_loop remains THE loop — ui/session must keep importing
        # SessionMemory + minimal_memory_for_prompt from main (no copy).
        sys.path.insert(0, BASE)
        import main
        self.assertTrue(callable(main.run_loop))
        self.assertTrue(hasattr(main, "SessionMemory"))
        self.assertTrue(hasattr(main, "minimal_memory_for_prompt"))
        import ui.session as usession
        self.assertIs(usession.SessionMemory, main.SessionMemory)
        self.assertIs(usession.minimal_memory_for_prompt, main.minimal_memory_for_prompt)


if __name__ == "__main__":
    unittest.main()
