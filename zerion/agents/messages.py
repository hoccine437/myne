# agents/messages.py
"""Canonical structured agent message schema.

Every coordinator/agent exchange that matters is carried in this
dataclass — no free-form agent-to-agent corridors. Fields match the
required spec (task_id/agent_id/parent/objective/context/inputs/
capabilities/permissions/actions/results/confidence/evidence/errors/
status/timestamps).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict


@dataclass
class AgentMessage:
    objective: str
    agent_id: str
    task_id: str
    parent_task_id: str = ""
    context: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)
    capabilities_required: tuple = ()
    permissions_required: tuple = ()
    actions: tuple = ()
    results: tuple = ()
    confidence: float = 0.0
    evidence: tuple = ()
    errors: tuple = ()
    status: str = "created"
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @staticmethod
    def new(objective: str, agent_id: str, task_id: str | None = None,
            parent_task_id: str = "", **kw) -> "AgentMessage":
        return AgentMessage(objective=objective, agent_id=agent_id,
                            task_id=task_id or uuid.uuid4().hex[:12],
                            parent_task_id=parent_task_id, **kw)

    def to_dict(self) -> dict:
        return asdict(self)
