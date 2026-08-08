# comms/__init__.py
"""Zerion Communication Layer — package surface.

Subsystems: models (unified message/draft), base+registry (connectors),
classify, store (shared DB tables), inbox (unified views), reply (drafts),
approvals (level ladder), ratelimit (anti-spam rails), audit (trail),
verify (checklists), calendar, workflow (+engine), scheduler (trigger pump),
engine (the only send path).

Everything outbound exits through comms.engine.send_draft — there is no
second send path anywhere in the package.
"""
