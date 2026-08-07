import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ast
import importlib
import os


# ---------------------------------------------------------------------------
# Idle-tick maintenance wiring (this session's fix)
# ---------------------------------------------------------------------------

def test_idle_tick_reports_weak_capabilities_without_duplicating_consolidation():
    """main.py's idle branch reports runtime_intelligence.quality.weak()
    directly, reusing the CapabilityQuality tracker RuntimeIntelligence
    already maintains every turn -- it must NOT construct its own
    BackgroundMaintenance/MemoryOptimizer instance, since
    learning.background.BackgroundLearning.run_once() already calls
    MemoryOptimizer().consolidate() on the same idle tick. Two
    consolidate() calls per idle tick would be a duplicate implementation
    of the same responsibility."""
    from intelligence.runtime import RuntimeIntelligence

    runtime = RuntimeIntelligence()
    # Simulate a few turns so quality has real uses/reliability data.
    for i in range(3):
        runtime.prepare(f"goal {i}", [])
        runtime.complete(f"goal {i}", "response", 0.01, [])

    weak = runtime.quality.weak()
    assert isinstance(weak, list)

    # Confirm main.py's idle branch actually calls this exact attribute
    # path, not a separately-instantiated maintenance object.
    main_src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    assert "runtime_intelligence.quality.weak()" in main_src
    assert "BackgroundMaintenance(" not in main_src


def test_intelligence_maintenance_module_removed():
    # intelligence/maintenance.py's BackgroundMaintenance duplicated
    # MemoryOptimizer().consolidate() (already called by
    # learning.background.BackgroundLearning.run_once()). Its one useful
    # behavior (weak-capability reporting) was wired in directly via
    # RuntimeIntelligence.quality instead. The file should not exist.
    root = Path(__file__).resolve().parents[1]
    assert not (root / "intelligence" / "maintenance.py").exists()


def test_phone_permissions_module_removed():
    # phone/permissions.py's PermissionManager.explain() duplicated the
    # unavailability message phone.adapter.TermuxAdapter.run() already
    # produces at the point of actual use. The file should not exist.
    root = Path(__file__).resolve().parents[1]
    assert not (root / "phone" / "permissions.py").exists()


def test_engineering_package_removed():
    # engineering/* was a set of thin, entirely unreferenced facades over
    # the dormant evolution engine -- zero call sites anywhere, including
    # tests. The whole package should be gone.
    root = Path(__file__).resolve().parents[1]
    assert not (root / "engineering").exists()


# ---------------------------------------------------------------------------
# Project-health guard: every module still imports; no dangling references
# to files removed during this session's dead-code cleanup.
# ---------------------------------------------------------------------------

_REMOVED_SYMBOLS = (
    "EngineeringArchitect", "LightweightProfiler",
    "IncrementalIndexer", "ExperienceMemory", "KnowledgeMemory",
    "WorkingMemory", "PermissionManager", "IntegrationTests",
    "PerformanceValidator", "RegressionTests", "ArchitectureValidator",
    "BackgroundMaintenance(",
)


def test_no_dangling_references_to_removed_modules():
    root = Path(__file__).resolve().parents[1]
    self_path = Path(__file__).resolve()
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        if "/.git" in dirpath or "__pycache__" in dirpath:
            continue
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            path = Path(dirpath) / fname
            if path.resolve() == self_path:
                continue  # this file legitimately names the removed symbols
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for symbol in _REMOVED_SYMBOLS:
                if symbol in text:
                    hits.append((str(path), symbol))
    assert hits == [], f"dangling references to removed symbols: {hits}"


def test_every_module_still_imports_cleanly():
    root = Path(__file__).resolve().parents[1]
    failed = []
    for dirpath, dirnames, filenames in os.walk(root):
        if "/.git" in dirpath or "__pycache__" in dirpath or "/tests" in dirpath:
            continue
        for fname in filenames:
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            rel = os.path.relpath(os.path.join(dirpath, fname), root)
            modname = rel[:-3].replace(os.sep, ".")
            try:
                importlib.import_module(modname)
            except Exception as e:
                failed.append((modname, repr(e)))
    assert failed == [], f"import failures: {failed}"


def test_no_circular_import_edges_introduced_this_session():
    # This session's changes were removals plus two small additions inside
    # main.py's existing idle branch -- no new import edges were added
    # anywhere. The one known package-level cycle (memory <-> intelligence,
    # via memory/intelligence.py -> intelligence/world.py and
    # intelligence/runtime.py -> memory/intelligence.py) is pre-existing
    # and unrelated to this session; it does not break import order in
    # either direction, which this test confirms directly rather than
    # asserting the cycle doesn't exist.
    import memory.intelligence      # noqa: F401
    import intelligence.runtime     # noqa: F401
    importlib.reload(memory.intelligence)
    importlib.reload(intelligence.runtime)


if __name__ == "__main__":
    test_idle_tick_reports_weak_capabilities_without_duplicating_consolidation()
    test_intelligence_maintenance_module_removed()
    test_phone_permissions_module_removed()
    test_engineering_package_removed()
    test_no_dangling_references_to_removed_modules()
    test_every_module_still_imports_cleanly()
    test_no_circular_import_edges_introduced_this_session()
    print("All core-stabilization integration tests passed.")
