# tools/file_tools.py
"""
Filesystem tools. Read/write/list/search are non-destructive and run
immediately. Move/copy/delete/rename are marked destructive — the Tool
Manager requires explicit user confirmation before they execute
(tools/manager.py handles this; each tool here just declares the flag).

All paths are expanded/resolved but not otherwise sandboxed — Mark-X Lite
runs with the permissions of whatever user starts it, same as any other
terminal tool. Be careful what you point it at.
"""

import os
import shutil
import tempfile

from tools.base import Tool, ToolResult

_MAX_READ_BYTES = 200_000  # ~200KB cap so a huge file can't blow up context/RAM


def _resolve(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


class FileReaderTool(Tool):
    name = "read_file"
    description = "Read the text contents of a file."
    parameters = {"path": "path to the file"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        path = str(parameters.get("path", "")).strip()
        if not path:
            return ToolResult.fail(error="missing_parameter", message="No path provided.")
        full = _resolve(path)
        if not os.path.isfile(full):
            return ToolResult.fail(error="not_found", message=f"No such file: {path}")
        try:
            size = os.path.getsize(full)
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(_MAX_READ_BYTES)
            truncated = size > _MAX_READ_BYTES
            msg = content if not truncated else content + "\n... (truncated)"
            return ToolResult.ok(data=content, message=msg)
        except Exception as e:
            return ToolResult.fail(error="read_failed", message=str(e))


class FileWriterTool(Tool):
    name = "write_file"
    description = "Write (or overwrite) text content to a file."
    parameters = {"path": "path to the file", "content": "text content to write"}
    destructive = True  # overwriting an existing file is irreversible

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        path = str(parameters.get("path", "")).strip()
        content = parameters.get("content", "")
        if not path:
            return ToolResult.fail(error="missing_parameter", message="No path provided.")
        full = _resolve(path)
        tmp_path = None
        try:
            directory = os.path.dirname(full) or "."
            os.makedirs(directory, exist_ok=True)
            # Same-directory replace is atomic on Linux/Termux: a crash never
            # leaves an existing target half-written.
            fd, tmp_path = tempfile.mkstemp(prefix=".zerion-", suffix=".tmp", dir=directory, text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(content))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, full)
            return ToolResult.ok(data=full, message=f"Wrote {len(str(content))} characters to {path}.")
        except Exception as e:
            return ToolResult.fail(error="write_failed", message=str(e))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


class FileSearchTool(Tool):
    name = "search_files"
    description = "Search for files by name pattern under a directory."
    parameters = {"directory": "directory to search", "pattern": "substring to match in filenames"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        directory = str(parameters.get("directory", ".")).strip() or "."
        pattern = str(parameters.get("pattern", "")).strip().lower()
        full_dir = _resolve(directory)
        if not os.path.isdir(full_dir):
            return ToolResult.fail(error="not_found", message=f"No such directory: {directory}")
        matches = []
        try:
            for root, _, files in os.walk(full_dir):
                for name in files:
                    if not pattern or pattern in name.lower():
                        matches.append(os.path.join(root, name))
                if len(matches) >= 100:
                    break
            msg = f"Found {len(matches)} match(es)." if matches else "No matches found."
            return ToolResult.ok(data=matches, message=msg)
        except Exception as e:
            return ToolResult.fail(error="search_failed", message=str(e))


class DirectoryListTool(Tool):
    name = "list_directory"
    description = "List files and folders in a directory."
    parameters = {"path": "directory path (default current directory)"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        path = str(parameters.get("path", ".")).strip() or "."
        full = _resolve(path)
        if not os.path.isdir(full):
            return ToolResult.fail(error="not_found", message=f"No such directory: {path}")
        try:
            entries = sorted(os.listdir(full))
            msg = ", ".join(entries) if entries else "(empty directory)"
            return ToolResult.ok(data=entries, message=msg)
        except Exception as e:
            return ToolResult.fail(error="list_failed", message=str(e))


class CreateFolderTool(Tool):
    name = "create_folder"
    description = "Create a new directory (including parent directories)."
    parameters = {"path": "directory path to create"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        path = str(parameters.get("path", "")).strip()
        if not path:
            return ToolResult.fail(error="missing_parameter", message="No path provided.")
        full = _resolve(path)
        try:
            os.makedirs(full, exist_ok=True)
            return ToolResult.ok(data=full, message=f"Created directory {path}.")
        except Exception as e:
            return ToolResult.fail(error="create_failed", message=str(e))


class MoveFileTool(Tool):
    name = "move_file"
    description = "Move or rename a file or directory."
    parameters = {"source": "current path", "destination": "new path"}
    destructive = True

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        src = str(parameters.get("source", "")).strip()
        dst = str(parameters.get("destination", "")).strip()
        if not src or not dst:
            return ToolResult.fail(error="missing_parameter", message="Both source and destination are required.")
        full_src, full_dst = _resolve(src), _resolve(dst)
        if not os.path.exists(full_src):
            return ToolResult.fail(error="not_found", message=f"No such path: {src}")
        try:
            shutil.move(full_src, full_dst)
            return ToolResult.ok(data=full_dst, message=f"Moved {src} to {dst}.")
        except Exception as e:
            return ToolResult.fail(error="move_failed", message=str(e))


class CopyFileTool(Tool):
    name = "copy_file"
    description = "Copy a file to a new location."
    parameters = {"source": "path to copy", "destination": "destination path"}
    destructive = True  # can silently overwrite an existing destination file

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        src = str(parameters.get("source", "")).strip()
        dst = str(parameters.get("destination", "")).strip()
        if not src or not dst:
            return ToolResult.fail(error="missing_parameter", message="Both source and destination are required.")
        full_src, full_dst = _resolve(src), _resolve(dst)
        if not os.path.isfile(full_src):
            return ToolResult.fail(error="not_found", message=f"No such file: {src}")
        try:
            shutil.copy2(full_src, full_dst)
            return ToolResult.ok(data=full_dst, message=f"Copied {src} to {dst}.")
        except Exception as e:
            return ToolResult.fail(error="copy_failed", message=str(e))


class DeleteFileTool(Tool):
    name = "delete_file"
    description = "Permanently delete a file."
    parameters = {"path": "path to the file to delete"}
    destructive = True

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        path = str(parameters.get("path", "")).strip()
        if not path:
            return ToolResult.fail(error="missing_parameter", message="No path provided.")
        full = _resolve(path)
        if not os.path.isfile(full):
            return ToolResult.fail(error="not_found", message=f"No such file: {path}")
        try:
            os.remove(full)
            return ToolResult.ok(data=full, message=f"Deleted {path}.")
        except Exception as e:
            return ToolResult.fail(error="delete_failed", message=str(e))


class RenameFileTool(Tool):
    name = "rename_file"
    description = "Rename a file or directory in place."
    parameters = {"path": "current path", "new_name": "new filename (not a full path)"}
    destructive = True

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        path = str(parameters.get("path", "")).strip()
        new_name = str(parameters.get("new_name", "")).strip()
        if not path or not new_name:
            return ToolResult.fail(error="missing_parameter", message="Both path and new_name are required.")
        full = _resolve(path)
        if not os.path.exists(full):
            return ToolResult.fail(error="not_found", message=f"No such path: {path}")
        new_full = os.path.join(os.path.dirname(full), new_name)
        try:
            os.rename(full, new_full)
            return ToolResult.ok(data=new_full, message=f"Renamed to {new_name}.")
        except Exception as e:
            return ToolResult.fail(error="rename_failed", message=str(e))
