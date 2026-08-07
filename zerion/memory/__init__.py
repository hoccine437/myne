# memory/__init__.py
"""Long-term memory subsystem.

memory_manager  — canonical persistence (atomic writes, backup, recovery)
intelligence    — episodic/graph memory used by runtime intelligence
long_term       — legacy compatibility API over knowledge.manager

Note: load/update happen through memory_manager; this file only marks the
package (it previously worked as an implicit namespace package).
"""
