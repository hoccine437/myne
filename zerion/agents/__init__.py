# agents/__init__.py
"""Zerion agents: dynamically instantiated workers of five fixed types.

"Five types ≠ five agents": each type can have N live instances, bounded
by resources and safety — not by the count of types. Everything an agent
does flows through the existing Tool Manager (same discovery, same
Constitution policy) or the Knowledge layer; agents never call Android,
the filesystem, or the network directly, and destructive tools are
refused outright (confirmations belong to the supervised user path).

Public surface: AGENT_TYPES, AgentType, agent_pool (singleton from
agents.service). NOTE: never export a bare name `pool` here — it would
shadow the agents.pool submodule on the package object.
"""

from agents.types import AGENT_TYPES, AgentType           # noqa: F401
from agents.service import pool as agent_pool             # noqa: F401
