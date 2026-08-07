# agents/service.py
"""Process-wide agent pool singleton (mirrors the Core's tool_manager /
planner singleton style — one pool per process)."""

from agents.pool import AgentPool

pool = AgentPool()
