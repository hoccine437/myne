# tests/test_final_features.py
"""Verification for the final-phase subsystems: agents, skills, personality,
device-state (phone body), deepened reasoning, and evolution protections."""

import os
import threading
import sys
import tempfile
import time
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)


# ======================================================================
# AGENTS
# ======================================================================

class AgentPoolTests(unittest.TestCase):
    def setUp(self):
        from agents.pool import AgentPool
        self.pool = AgentPool(max_agents=3)

    def tearDown(self):
        self.pool.shutdown()

    def test_spawn_and_complete(self):
        r = self.pool.spawn("monitor", {"tool": "get_time"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["agent"]["status"], "completed")
        self.assertIn("message", r["agent"]["result"])

    def test_parallel_work_aggregation(self):
        out = self.pool.delegate([
            {"type": "monitor", "task": {"tool": "get_time"}},
            {"type": "controller", "task": {"tool": "cpu_info"}},
            {"type": "verifier", "task": {"tool": "calculate", "parameters": {"expression": "6*7"}}},
        ])
        ids = [x["agent"]["id"] for x in out["results"] if x.get("agent")]
        agg = self.pool.collect(ids)
        self.assertEqual(agg["succeeded"], 3, str(agg))
        self.assertEqual(agg["failed"], 0)

    def test_execution_bounded_backlog_capable(self):
        """Instances queue (creation unbounded by hardcoded counts); execution
        is resource-bounded; backlog over max_pending is refused."""
        from agents.pool import AgentPool
        pool = AgentPool(max_agents=1, resources={"cores": 1, "mem_gb": 1})
        self.assertEqual(pool.max_pending, 16)
        hold = threading.Event()
        orig_execute = pool._execute

        def slow(agent):
            hold.wait(2.0)
            orig_execute(agent)
        pool._execute = slow
        try:
            results = [pool.spawn("monitor", {"tool": "get_time"}, wait=False)
                       for _ in range(25)]
            accepted = [r for r in results if r.get("ok")]
            rejected = [r for r in results if not r.get("ok")]
            self.assertEqual(len(accepted), 16, f"{len(accepted)} accepted")
            self.assertTrue(rejected, "backlog bound must refuse")
            self.assertEqual(rejected[0]["error"], "backlog")
        finally:
            hold.set()
        for r in [r for r in results if r.get("ok")]:
            pool.wait(r["agent"]["id"], timeout=10)
        done = pool.collect([r["agent"]["id"] for r in accepted])
        self.assertEqual(done["succeeded"], 16)
        pool.shutdown()

    def test_capacity_scales_with_resources(self):
        from agents.pool import AgentPool, _effective_capacity
        big = AgentPool(resources={"cores": 64, "mem_gb": 128})
        small = AgentPool(resources={"cores": 2, "mem_gb": 2})
        self.assertGreaterEqual(big.max_agents, 32)
        self.assertEqual(small.max_agents, 4)
        # big-host acceptance of 100 researcher instances, no fixed cap
        r = big.spawn("researcher", {"query": "noop"}, wait=False)
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(big.max_pending, 100)
        big.shutdown(); small.shutdown()
        self.assertEqual(_effective_capacity(1, 1), 2)

    def test_destructive_tools_are_refused(self):
        r = self.pool.spawn("coder", {"tool": "delete_file", "parameters": {"path": "/x"}})
        self.assertFalse(r["ok"])
        self.assertEqual(r["agent"]["status"], "failed")
        self.assertIn("whitelist", r["agent"]["error"])

    def test_failure_isolation_and_restart(self):
        r = self.pool.spawn("monitor", {"tool": "no_such_tool_xyz"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["agent"]["status"], "failed")
        restarted = self.pool.restart(r["agent"]["id"])
        self.assertFalse(restarted["ok"])  # same bad tool fails again — but cleanly
        self.assertEqual(restarted["agent"]["status"], "failed")
        twice = self.pool.restart(r["agent"]["id"])
        # restart budget: lineage capped at one restart
        self.assertIn(twice.get("error"), ("restart_limit", "not_found", "capacity"))
        # pool still healthy after the failures
        ok = self.pool.spawn("monitor", {"tool": "get_date"})
        self.assertTrue(ok["ok"])

    def test_whitelist_boundary(self):
        r = self.pool.spawn("controller", {"tool": "run_shell", "parameters": {"command": "echo"}})
        self.assertEqual(r["agent"]["status"], "failed")
        self.assertIn("whitelist", r["agent"]["error"])

    def test_memory_search_only_for_allowed_types(self):
        r = self.pool.spawn("researcher", {"query": "zerion"})
        self.assertTrue(r["ok"])
        r2 = self.pool.spawn("controller", {"query": "zerion"})
        self.assertEqual(r2["agent"]["status"], "failed")

    def test_cleanup_reaps_finished(self):
        import agents.pool as pool_mod
        old_ttl = pool_mod._AGENT_TTL
        pool_mod._AGENT_TTL = 0.0
        try:
            self.pool.spawn("monitor", {"tool": "get_time"})
            time.sleep(0.05)
            self.assertGreaterEqual(self.pool.reap(), 1)
        finally:
            pool_mod._AGENT_TTL = old_ttl

    def test_unknown_type(self):
        self.assertFalse(self.pool.spawn("mastermind", {"tool": "get_time"})["ok"])

    def test_tool_manager_surface(self):
        """The Core reaches agents exactly like any other tool."""
        from tools.manager import tool_manager
        result = tool_manager.execute("agent_delegate", {
            "agent_type": "verifier",
            "task": {"tool": "calculate", "parameters": {"expression": "2+5"}},
        })
        self.assertTrue(result.success, result.message)
        self.assertIn("7", result.message)
        stats = tool_manager.execute("agent_status", {})
        self.assertTrue(stats.success)

    def test_destructive_confirmation_flow_untouched_by_agents(self):
        """The sanctioned path still gates destructive tools for humans."""
        from tools.manager import tool_manager
        result = tool_manager.execute("delete_file", {"path": "/tmp/agent-never-this"})
        self.assertEqual(result.error, "confirmation_required")
        tool_manager.cancel_pending_confirmation()


# ======================================================================
# SKILLS
# ======================================================================

class SkillTests(unittest.TestCase):
    def setUp(self):
        from skills.manager import SkillManager
        self.mgr = SkillManager()

    def test_legacy_routing_preserved(self):
        # the exact test_phase4 contract
        self.assertEqual(self.mgr.select("debug python code").name, "software_engineering")

    def test_four_core_domains(self):
        for phrase, want in (
            ("analyze stock market trends", "financial_markets"),
            ("design a resistor circuit for arduino", "electronics"),
            ("review this python program", "software_engineering"),
            ("tell me about ancient history", "history"),
        ):
            self.assertEqual(self.mgr.select(phrase).name, want)

    def test_ten_additional_domains_routable(self):
        cases = (
            ("solve the matrix algebra problem", "mathematics"),
            ("compute the kinetic energy of this mass", "physics"),
            ("balance this chemical reaction", "chemistry"),
            ("what does a vaccine dosage mean", "health_information"),
            ("explain this copyright license", "legal_information"),
            ("suggest an ingredient substitution for the recipe", "culinary"),
            ("translate this sentence into spanish", "languages"),
            ("when did the roman empire fall", "history"),
            ("compute the torque on this gear shaft", "mechanical_engineering"),
            ("help me rewrite this essay headline", "writing"),
        )
        for phrase, want in cases:
            got = self.mgr.select(phrase).name
            self.assertEqual(got, want, f"{phrase!r} routed to {got!r}")

    def test_total_skill_count(self):
        self.assertGreaterEqual(len(self.mgr.names()), 14)

    def test_tool_surface(self):
        from tools.manager import tool_manager
        r = tool_manager.execute("skill_route", {"text": "compute a derivative"})
        self.assertTrue(r.success)
        self.assertEqual(r.data["skill"], "mathematics")
        lst = tool_manager.execute("skill_list", {})
        self.assertGreaterEqual(len(lst.data), 14)


# ======================================================================
# PERSONALITY
# ======================================================================

class PersonalityTests(unittest.TestCase):
    def setUp(self):
        import memory.memory_manager as mm
        import personality
        self.p = personality
        # personality persists through memory — redirect to a temp file
        # so tests never write into the real memory.json
        import importlib
        self._mm = mm
        self._orig_mem, self._orig_bak = mm.MEMORY_PATH, mm.BACKUP_PATH
        self._tmpdir = tempfile.mkdtemp()
        mm.MEMORY_PATH = os.path.join(self._tmpdir, "memory.json")
        mm.BACKUP_PATH = mm.MEMORY_PATH + ".bak"
        personality._current = None  # reload from redirected store
        self.p.set_mode(personality.NORMAL)

    def tearDown(self):
        self.p.set_mode(self.p.NORMAL)
        self.p._current = None
        self._mm.MEMORY_PATH, self._mm.BACKUP_PATH = self._orig_mem, self._orig_bak
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_switch_both_directions(self):
        ack = self.p.set_mode(self.p.SERIOUS)
        self.assertIn("Serious", ack)
        self.assertEqual(self.p.current(), "serious")
        self.assertTrue(self.p.persona_rules())
        ack = self.p.set_mode(self.p.NORMAL)
        self.assertIn("Normal", ack)
        self.assertEqual(self.p.current(), "normal")
        self.assertEqual(self.p.persona_rules(), ())

    def test_command_palette_phrase_and_slash(self):
        # serious activation is AUTHENTICATED (security contract upgrade):
        # the palette still recognizes the phrases, but activation now
        # requires the password handshake; deactivation stays free
        from intent import commands
        self.assertTrue(commands.is_command("START SERIOUS MODE"))
        self.assertTrue(commands.is_command("/serious"))
        out = commands.handle("start serious mode", None, {})
        self.assertIn("Serious", out)
        self.assertIn("authentication", out.lower())
        self.assertTrue(commands.pending_secret_input())
        out2 = commands.handle("nano 808", None, {})
        self.assertIn("SERIOUS MODE: ON", out2)
        self.assertTrue(commands.is_command("STOP SERIOUS MODE"))
        out3 = commands.handle("Stop Serious Mode", None, {})
        self.assertIn("Normal", out3)
        # critical: natural language starting with 'start' is NOT swallowed
        self.assertFalse(commands.is_command("start a timer for my run"))

    def test_rules_reach_prompt_channel(self):
        from cognition import CognitiveEngine
        engine = CognitiveEngine()
        before = engine.prepare("plan today").mode.rules
        self.p.set_mode(self.p.SERIOUS)
        after = engine.prepare("plan today").mode.rules
        self.assertGreater(len(after), len(before))
        self.assertTrue(any("boundaries remain" in r for r in after),
                        "serious mode must carry the boundary-preservation rule")
        self.p.set_mode(self.p.NORMAL)

    def test_boundaries_unchanged_in_serious_mode(self):
        self.p.set_mode(self.p.SERIOUS)
        from constitution.policy import Constitution
        decision = Constitution().evaluate("execute_shell")
        self.assertTrue(decision.requires_approval,
                        "any consequential action still needs approval")
        self.p.set_mode(self.p.NORMAL)


# ======================================================================
# PHONE BODY (device state)
# ======================================================================

class DeviceStateTests(unittest.TestCase):
    def test_probe_shape_and_honesty(self):
        from phone.device import probe_device
        d = probe_device()
        for key in ("os", "arch", "is_termux", "is_android", "is_mobile",
                    "cpu", "memory", "storage", "battery", "network",
                    "screen", "input", "io", "termux_api", "lifecycle"):
            self.assertIn(key, d)
        self.assertIn(d["arch"], ("arm64", "x86_64", "arm32", "x86", "unknown"))
        # honest unknowns allowed, but structure is complete
        self.assertIsInstance(d["io"], dict)
        self.assertIsInstance(d["input"]["touch"], bool)

    def test_tool_surface(self):
        from tools.manager import tool_manager
        r = tool_manager.execute("device_state", {})
        self.assertTrue(r.success, r.message)
        self.assertIn("Device:", r.message)
        self.assertIn("os", r.data)

    def test_termux_feature_flag(self):
        from phone import device
        old = os.environ.get("PREFIX")
        try:
            os.environ["PREFIX"] = "/data/data/com.termux/files/usr"
            # is_termux reads env at call time
            self.assertTrue(device.is_termux())
        finally:
            if old is None:
                os.environ.pop("PREFIX", None)
            else:
                os.environ["PREFIX"] = old


# ======================================================================
# DEEPENED REASONING (multi-path hypotheses)
# ======================================================================

class DeepReasoningTests(unittest.TestCase):
    def test_analytic_goals_get_multiple_paths(self):
        from cognition.reasoning import CognitiveReasoningEngine
        result = CognitiveReasoningEngine().reason("why would my offline AI answer wrong")
        self.assertGreaterEqual(len(result.inferences), 4,
                                "privacy heuristic + 3 analytic paths expected")
        statuses = {i.status for i in result.inferences}
        self.assertEqual(statuses, {"hypothesis"})
        self.assertTrue(0.35 <= result.confidence <= 0.9)

    def test_simple_goals_stay_shallow(self):
        from cognition.reasoning import CognitiveReasoningEngine
        result = CognitiveReasoningEngine().reason("hello there")
        self.assertEqual(len(result.inferences), 0)
        self.assertGreaterEqual(result.confidence, 0.35)

    def test_legacy_reasoning_contract_intact(self):
        # covers the test_reasoning.py guarantee
        from cognition.reasoning import CognitiveReasoningEngine
        result = CognitiveReasoningEngine().reason("I am building an offline AI")
        self.assertTrue(result.inferences[0].status == "hypothesis")
        self.assertTrue(0 < result.confidence < 1)


# ======================================================================
# EVOLUTION — deploy/rollback + protected bypass attempts
# ======================================================================

class EvolutionProtectionTests(unittest.TestCase):
    def test_full_deploy_and_rollback_cycle(self):
        from evolution.engine import EvolutionEngine
        with tempfile.TemporaryDirectory() as d:
            root = os.path.abspath(d)
            os.makedirs(os.path.join(root, "docs"), exist_ok=True)
            target = os.path.join(root, "docs", "note.txt")
            with open(target, "w") as f:
                f.write("original")

            changes = {
                "docs/note.txt": "improved",
                "docs/new_module.py": "VALUE = 42\n",  # compile check passes → one staged test
            }
            engine = EvolutionEngine(root)
            manifest, review, results = engine.prepare("documentation improvement", changes)
            self.assertTrue(review.approved, f"review unexpectedly rejected: {review.issues}")
            self.assertTrue(results and all(r.passed for r in results),
                            "staged compile checks must pass")
            # unapproved → refused
            with self.assertRaises(PermissionError):
                engine.deploy(manifest, results, approved=False)
            # approved → deployed
            engine.deploy(manifest, results, approved=True)
            with open(target) as f:
                self.assertEqual(f.read(), "improved")
            self.assertTrue(os.path.exists(os.path.join(root, "docs", "new_module.py")))
            # rollback restores the original and removes added files
            from evolution.rollback import RollbackEngine
            files = RollbackEngine(root).rollback(manifest.id)
            self.assertIn("docs/note.txt", files)
            with open(target) as f:
                self.assertEqual(f.read(), "original")
            self.assertFalse(os.path.exists(os.path.join(root, "docs", "new_module.py")))

    def test_protected_paths_cannot_be_evolved(self):
        from evolution.manifest import is_protected, UpgradeManifest
        for path in ("main.py", "constitution/constitution.txt", "config.py",
                     "prompt.txt", "memory/memory.json", "planner/planner.py", ".env"):
            self.assertTrue(is_protected(path), path)
        m = UpgradeManifest(reason="x", files=["main.py"], risk="high",
                            dependencies=[], expected_improvement="x",
                            rollback_strategy="rollback", complexity="trivial")
        with self.assertRaises(PermissionError):
            m.validate()

    def test_constitution_integrity_still_verified(self):
        from constitution.constitution import ConstitutionEngine
        self.assertTrue(ConstitutionEngine.verify_lock())


if __name__ == "__main__":
    unittest.main()
