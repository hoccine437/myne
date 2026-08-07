"""Regression tests for narrow production hardening fixes."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow both direct `python tests/test_hardening.py` and test-runner imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.base import Tool, ToolResult
from tools.file_tools import FileWriterTool
from tools.manager import ToolManager
import memory.memory_manager as memory_manager


def test_invalid_numeric_config_recovers() -> None:
    env = dict(os.environ, VOICE_VOLUME="not-a-number", REQUEST_TIMEOUT="0")
    result = subprocess.run([sys.executable, "-c", "import config; print(config.validate())"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "not a number" in result.stdout and "below 1" in result.stdout


def test_atomic_file_writer_replaces_complete_content() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "value.txt"
        path.write_text("old", encoding="utf8")
        result = FileWriterTool().execute({"path": str(path), "content": "new"})
        assert result.success and path.read_text(encoding="utf8") == "new"
        assert not list(Path(directory).glob(".zerion-*.tmp"))


def test_memory_first_save_recovers_from_corruption() -> None:
    old_path, old_backup = memory_manager.MEMORY_PATH, memory_manager.BACKUP_PATH
    try:
        with tempfile.TemporaryDirectory() as directory:
            memory_manager.MEMORY_PATH = str(Path(directory) / "memory.json")
            memory_manager.BACKUP_PATH = memory_manager.MEMORY_PATH + ".bak"
            memory_manager.save_memory({"identity": {"name": {"value": "Ada"}}})
            Path(memory_manager.MEMORY_PATH).write_text("{corrupt", encoding="utf8")
            assert memory_manager.load_memory()["identity"]["name"]["value"] == "Ada"
    finally:
        memory_manager.MEMORY_PATH, memory_manager.BACKUP_PATH = old_path, old_backup


def test_confirmation_preserves_parameter_types() -> None:
    class TypedDestructiveTool(Tool):
        name = "typed"; description = "test"; parameters = {}; destructive = True
        def available(self): return True
        def execute(self, parameters): return ToolResult.ok(data=parameters)
    manager = ToolManager(); manager._tools = {"typed": TypedDestructiveTool()}
    params = {"items": [1, {"safe": True}], "count": 2}
    assert manager.execute("typed", params).error == "confirmation_required"
    result = manager.confirm_pending()
    assert result.success and result.data == params


def run_all() -> None:
    test_invalid_numeric_config_recovers()
    test_atomic_file_writer_replaces_complete_content()
    test_memory_first_save_recovers_from_corruption()
    test_confirmation_preserves_parameter_types()

if __name__ == "__main__": run_all()
