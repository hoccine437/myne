# tools/registry.py
"""
Discovers every Tool subclass defined in tools/*.py automatically.

Adding a new tool means dropping one file into tools/ that defines a
Tool subclass — nothing else needs to change. This module walks the
package, imports each module, and picks up any Tool subclass it finds.

Discovery happens once, lazily, on first access — not at import time —
so simply importing this module costs nothing.
"""

import importlib
import inspect
import pkgutil

from tools.base import Tool

_EXCLUDED_MODULES = {"base", "manager", "registry", "__init__"}

_cache = None  # populated on first discover() call


def discover() -> dict:
    """Return {tool.name: tool_instance} for every valid tool found in
    tools/. Cached after the first call — call _invalidate() in tests if
    you need a fresh scan."""
    global _cache
    if _cache is not None:
        return _cache

    found = {}
    package = importlib.import_module("tools")

    for _, module_name, is_pkg in pkgutil.iter_modules(package.__path__):
        if is_pkg or module_name in _EXCLUDED_MODULES:
            continue
        try:
            module = importlib.import_module(f"tools.{module_name}")
        except Exception as e:
            print(f"WARNING: tool module 'tools/{module_name}.py' failed to import: {e}")
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Tool or not issubclass(obj, Tool):
                continue
            if obj.__module__ != module.__name__:
                continue  # skip re-exported/imported classes from other modules

            try:
                instance = obj()
            except Exception as e:
                print(f"WARNING: tool class '{obj.__name__}' in tools/{module_name}.py "
                      f"failed to instantiate: {e}")
                continue

            if not getattr(instance, "name", ""):
                print(f"WARNING: tool class '{obj.__name__}' in tools/{module_name}.py "
                      f"has no 'name' — skipped.")
                continue

            if instance.name in found:
                print(f"WARNING: duplicate tool name '{instance.name}' in "
                      f"tools/{module_name}.py — keeping the first one found.")
                continue

            found[instance.name] = instance

    _cache = found
    return found


def _invalidate() -> None:
    """Clear the discovery cache. Used by tests / hot-reload scenarios."""
    global _cache
    _cache = None
