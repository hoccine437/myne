# memory/memory_manager.py
"""
Memory persistence with atomic writes, automatic backup, and corruption
recovery. The public functions (load_memory, save_memory, update_memory)
are unchanged from the original -- callers (main.py) need no changes.

Reliability guarantees added in this hardening pass:
  - Atomic writes: every save writes to a temp file in the same directory,
    then atomically renames it over the real file (os.replace). A crash
    or power loss mid-write can never leave memory.json half-written --
    the rename either fully happens or doesn't happen at all.
  - Automatic backup: before each save, if a memory.json already exists,
    it's copied to memory.json.bak first. This means even a *logically*
    bad write (e.g. a bug that saves wrong data) has a one-generation-back
    recovery path, not just protection against write-time corruption.
  - Corruption recovery: if memory.json exists but fails to parse as
    valid JSON, load_memory automatically falls back to memory.json.bak
    before giving up and returning an empty structure. This is checked
    and logged, never silent.
"""

import json
import os
import shutil
from threading import Lock

import config
from core import logging as log

MEMORY_PATH = config.MEMORY_PATH
BACKUP_PATH = MEMORY_PATH + ".bak"
_lock = Lock()


def _empty_memory() -> dict:
    """Return an empty memory structure."""
    return {
        "identity": {},
        "preferences": {},
        "relationships": {},
        "emotional_state": {}
    }


def _try_load(path: str):
    """Load and parse one file. Returns the dict on success, or None on
    any failure (missing file, bad JSON, wrong shape). Never raises."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_memory() -> dict:
    """
    Load memory from disk. Recovery order:
      1. memory.json, if it exists and parses correctly
      2. memory.json.bak, if the primary file is missing or corrupted
      3. an empty structure, if neither is usable

    Falling back to the backup is logged as a warning so the person
    running the assistant knows recovery happened -- this is never
    silent, per "never corrupt memory" including never silently losing
    data without saying so.
    """
    with _lock:
        primary = _try_load(MEMORY_PATH)
        if primary is not None:
            return primary

        if os.path.exists(MEMORY_PATH):
            # File exists but didn't parse -- genuine corruption, not
            # just "never created yet". Try the backup before giving up.
            log.warning(f"{MEMORY_PATH} is corrupted or unreadable; attempting recovery from backup.")

        backup = _try_load(BACKUP_PATH)
        if backup is not None:
            log.warning(f"Recovered memory from {BACKUP_PATH}.")
            return backup

        if os.path.exists(MEMORY_PATH):
            log.error("Memory could not be recovered from primary or backup file; starting fresh.")

        return _empty_memory()


def save_memory(memory: dict) -> None:
    """
    Save memory to disk atomically, backing up the previous version
    first. Sequence:
      1. If memory.json currently exists, copy it to memory.json.bak
         (best-effort -- a backup failure doesn't block the save itself,
         since losing this turn's update would be worse than an
         out-of-date backup).
      2. Write the new content to a temp file in the same directory.
      3. Atomically rename the temp file over memory.json (os.replace).

    Step 3 is what makes this crash-safe: os.replace is atomic on both
    Linux and Android/Termux (same filesystem, same directory) -- there
    is no window where memory.json exists but is half-written.
    """
    if not isinstance(memory, dict):
        log.warning("save_memory called with a non-dict value; ignoring.")
        return

    memory_dir = os.path.dirname(MEMORY_PATH) or "."
    os.makedirs(memory_dir, exist_ok=True)

    with _lock:
        if os.path.exists(MEMORY_PATH):
            try:
                shutil.copy2(MEMORY_PATH, BACKUP_PATH)
            except Exception as e:
                log.warning(f"Could not update memory backup (continuing anyway): {e}")

        tmp_path = MEMORY_PATH + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, MEMORY_PATH)
            # The first successful save has no previous generation to copy
            # before replacement. Seed a recovery copy so later corruption
            # never turns an otherwise valid one-generation memory into loss.
            if not os.path.exists(BACKUP_PATH):
                shutil.copy2(MEMORY_PATH, BACKUP_PATH)
        except Exception as e:
            log.error(f"Failed to save memory: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


def _recursive_update(target: dict, updates: dict) -> bool:
    """Recursively merge updates into target memory. Returns True if changed."""
    changed = False

    for key, value in updates.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue

        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            entry = value if isinstance(value, dict) and "value" in value else {"value": value}
            if key not in target or target[key] != entry:
                target[key] = entry
                changed = True

    return changed


def update_memory(memory_update: dict) -> dict:
    """Merge LLM memory update into global memory and save."""
    if not isinstance(memory_update, dict):
        return load_memory()

    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)

    return memory
