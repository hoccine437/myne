# tests/test_integration_map.py
"""Integration-map fence: every production module imports cleanly and the
critical subsystems stay reachable from main.py.

This test guards the stabilisation contract mechanically:

* importing ANY module must not fail (catches broken imports,
  import-time side effects, hidden circulars when interacted with the
  current interpreter state)
* the critical pipeline modules must STAy reachable from main.py's static
  import graph — a regression here means main.py quietly stopped using a
  subsystem (the "disconnected critical module" failure mode)
* the known-not-on-hot-path set is explicit (legacy compat APIs, the
  supervised evolution engine, standalone utilities, alternate front-end
  entry points) — if a NEW module goes unreachable from main, this test
  fails and someone must classify it deliberately
"""

import ast
import importlib
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)

# --- every critical stage of main.py's pipeline -----------------------------
CRITICAL_PIPELINE = [
    "config",                    # configuration
    "core.logging",              # logging
    "constitution.constitution", # integrity + policy
    "llm",                       # prompt/response contract
    "api",                       # provider shim
    "providers.router",          # provider routing
    "memory.memory_manager",     # long-term memory
    "knowledge.manager",         # knowledge retrieval/storage
    "learning.engine",           # learning
    "learning.background",       # idle maintenance
    "cognition",                 # cognitive modes
    "intelligence.runtime",      # runtime intelligence
    "intelligence.critic",       # self-critic
    "phone.engine",              # phone body
    "personality",               # normal/serious persona switch
    "speech",                    # voice output
    "tools.manager",             # tool routing + confirmation flow
    "planner",                   # planning engine package
    "intent.commands",           # command palette
    "intent.engine",             # intent engine
]

# Documented deliberately-not-on-main.py's-hot-path modules (verified
# dormant-but-intentional in the stabilization audit):
KNOWN_DORMANT_PREFIXES = (
    "skills",          # legacy compatibility skill registry (tests use it)
    "memory.long_term",# phased-out long-term memory API (tests use it)
    "evolution",       # Phase-5 self-evolution engine: operator-invoked only
    "testing",         # test-runner service used by evolution + tests
    "constitution.evolution",  # evolution policy glue (used by phase5 path)
    "runtime",         # 24/7 service daemon (own entry point)
    "comms.scheduler", # trigger pump — driven by runtime/service maintenance + workflow tools (service cadence, not per-turn)
    "readiness_audit", # final readiness audit (own entry, operator-run)
    "setup",           # first-run bootstrap CLI (own entry point)
    "second_audit",        # release-gate audit tool (own entry point, dev-only)
    "connectivity_audit",  # final-gate connectivity audit (own entry point, dev-only)
    "arch_map",            # reconciliation protocol measurement harness (dev)
)


def _build_graph():
    from pathlib import Path
    files = {}
    for p in sorted(Path(BASE).rglob("*.py")):
        rel = str(p.relative_to(BASE))
        if rel.startswith(("tests/", "smoke/")) or "__pycache__" in rel:
            continue
        rel_path = Path(rel)
        parts = list(rel_path.with_suffix("").parts)
        mod = ".".join(parts[:-1]) if parts[-1] == "__init__" else ".".join(parts)
        files[mod] = p

    known = set(files)
    edges = {}
    for mod, path in files.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        pkg = mod.split(".") if path.name == "__init__.py" else mod.split(".")[:-1]
        raw = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    raw.add(a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    base = node.module.split(".") if node.module else []
                else:
                    base = pkg[:len(pkg) - node.level + 1] + (
                        node.module.split(".") if node.module else [])
                if base:
                    raw.add(".".join(base))
                    for alias in node.names:
                        raw.add(".".join(base + [alias.name]))
        segs = mod.split(".")
        for i in range(len(segs) - 1, 0, -1):
            raw.add(".".join(segs[:i]))  # package-init execution edge
        es = set()
        for t in raw:
            s = t.split(".")
            for i in range(len(s), 0, -1):
                cand = ".".join(s[:i])
                if cand in known and cand != mod:
                    es.add(cand)
                    break
        edges[mod] = es
    return known, edges


def _reachable(edges, *starts):
    seen, stack = set(), list(starts)
    while stack:
        m = stack.pop()
        if m in seen or m not in edges:
            continue
        seen.add(m)
        stack.extend(edges[m])
    return seen


class ImportSweepTests(unittest.TestCase):
    def test_every_module_imports(self):
        known, _ = _build_graph()
        failures = []
        for mod in sorted(known):
            if mod == "setup":
                continue  # bootstrap CLI — runs its own checks as a program
            try:
                importlib.import_module(mod)
            except Exception as e:
                failures.append(f"{mod}: {type(e).__name__}: {e}")
        self.assertEqual(failures, [], "modules failing to import:\n" + "\n".join(failures))

    def test_only_allowlisted_modules_unreachable(self):
        known, edges = _build_graph()
        # Tools are discovered dynamically by tools/registry — so every tool
        # module (and its import tree, e.g. agents/, phone/device.py) counts
        # as reachable from main through the Tool Manager.
        tool_modules = [m for m in known
                        if m.startswith("tools.") and m.split(".")[1] not in ("base", "manager", "registry")]
        # mcp servers ride the same discovery discipline through the gateway
        # (agents call them via mcp.gateway; they are registry-loaded, so the
        # static sweep needs the same treatment)
        mcp_server_modules = [m for m in known
                              if m.startswith("mcp.servers.")]
        main_reach = _reachable(edges, "main", *tool_modules, *mcp_server_modules)
        unexpected = [
            m for m in sorted(known - main_reach)
            if not any(m.startswith(prefix) for prefix in KNOWN_DORMANT_PREFIXES)
        ]
        self.assertEqual(unexpected, [],
            "Modules not reachable from main.py and not documented as dormant. "
            "Either wire them in, or add them to KNOWN_DORMANT_PREFIXES with a "
            "classification note:\n" + "\n".join(unexpected))

    def test_critical_pipeline_reachable(self):
        known, edges = _build_graph()
        main_reach = _reachable(edges, "main")
        tool_runtime = {m for m in known if m.startswith("tools.")}  # dynamic discovery
        missing = [m for m in CRITICAL_PIPELINE
                   if m not in main_reach and m not in tool_runtime]
        self.assertEqual(missing, [],
            "Critical pipeline modules no longer reachable from main.py: "
            + ", ".join(missing))

    def test_tools_discoverable(self):
        from tools.manager import tool_manager
        tools = tool_manager.list_tools()
        names = [t["name"] for t in tools]
        self.assertGreaterEqual(len(names), 20)
        for expected in ("run_shell", "run_python", "read_file", "write_file",
                         "list_directory", "delete_file", "calculate"):
            self.assertIn(expected, names)

    def test_config_surface_loads(self):
        import config
        # parse-safety net: validate() must never raise, and all key knobs exist
        self.assertIsInstance(config.validate(), list)
        for attr in ("GEMINI_MODEL", "GEMINI_URL", "MEMORY_PATH", "PROMPT_PATH",
                     "PLANNER_ENABLED", "ENABLE_SELF_CRITIC", "LOW_CONFIDENCE_THRESHOLD",
                     "MAXIMUM_IMPROVEMENT_ATTEMPTS", "REQUEST_TIMEOUT", "MAX_HISTORY",
                     "VOICE_ENABLED", "VOICE_NAME", "REQUEST_TIMEOUT"):
            self.assertTrue(hasattr(config, attr), f"missing config attr {attr}")

    def test_no_protected_file_modified(self):
        """The constitution lock must verify — protects main.py and the
        constitution corpus from accidental edits."""
        from constitution.constitution import ConstitutionEngine
        self.assertTrue(ConstitutionEngine.verify_lock())


if __name__ == "__main__":
    unittest.main()
