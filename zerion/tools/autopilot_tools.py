# tools/autopilot_tools.py
"""Owner override tools for the communication layer.

Trust-reducing operations (pause / estop / disable / clear queue) are
non-destructive safety actions: they must never wait on confirmation.
Trust-forwarding operations (resume / enable / graduate a platform out of
shadow) are destructive=confirmation-gated: they widen outbound authority.
"""

from __future__ import annotations

from tools.base import Tool, ToolResult


class CommPauseTool(Tool):
    name = "comm_pause"
    description = ("Immediately pause ALL autonomous/external communication "
                   "(drafts keep working; nothing sends until comm_resume).")
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms.overrides import pause_all
        pause_all("tool:comm_pause")
        return ToolResult.ok(message="Communication paused. Outbound actions are parked; "
                                     "use comm_resume to resume.")


class CommResumeTool(Tool):
    name = "comm_resume"
    description = "Resume communication after a pause or emergency stop."
    parameters = {}
    destructive = True   # re-enables outbound authority — confirmation gate applies

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms.overrides import resume
        resume()
        return ToolResult.ok(message="Communication resumed (pause and ESTOP cleared).")


class CommEstopTool(Tool):
    name = "comm_estop"
    description = ("EMERGENCY STOP: halt all external actions NOW and expire "
                   "every queued/pending send. Use when anything looks wrong.")
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms.overrides import estop
        out = estop("tool:comm_estop")
        return ToolResult.ok(
            data=out,
            message=f"EMERGENCY STOP engaged. All external actions halted; "
                    f"{out['queue_dropped']} queued item(s) dropped. "
                    f"Use comm_resume when safe.")


class CommOverrideTool(Tool):
    name = "comm_override"
    description = ("Scoped overrides: disable/enable a platform, contact or "
                   "workflow; graduate a platform out of shadow mode. Params: "
                   "op (disable_platform|enable_platform|disable_contact|"
                   "enable_contact|disable_workflow|enable_workflow|graduate|"
                   "ungraduate), target.")
    parameters = {"op": "override operation", "target": "platform / contact / workflow id"}
    destructive = True   # trust-forward ops widen authority — confirmation gate

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import overrides, quality
        p = parameters or {}
        op = str(p.get("op", ""))
        target = str(p.get("target", "")).strip()
        if not target:
            return ToolResult.fail("missing_parameter", "target is required")
        table = {
            "disable_platform": lambda: overrides.disable_platform(target, "tool"),
            "enable_platform": lambda: overrides.enable_platform(target),
            "disable_contact": lambda: overrides.disable_contact(target, "tool"),
            "enable_contact": lambda: overrides.enable_contact(target),
            "disable_workflow": lambda: overrides.disable_workflow(target, "tool"),
            "enable_workflow": lambda: overrides.enable_workflow(target),
            "graduate": lambda: quality.set_shadow(target, "graduated") or
                {"platform": target, "graduated": True},
            "ungraduate": lambda: quality.set_shadow(target, "shadow") or
                {"platform": target, "graduated": False},
        }
        fn = table.get(op)
        if fn is None:
            return ToolResult.fail("invalid_parameter",
                                   f"op must be one of: {', '.join(sorted(table))}")
        return ToolResult.ok(data=fn(), message=f"{op} {target} applied.")


class CommOutboxTool(Tool):
    name = "comm_outbox"
    description = "Inspect queued/pending outbound items (offline queue) with retry states."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import outbox
        rows = outbox.pending(limit=25)
        if not rows:
            return ToolResult.ok(message="Outbound queue is empty.")
        lines = [f"- [{r['status']}] {r['platform']}→{r['recipient']} "
                 f"attempts={r['attempts']} err={r['last_error'][:60] or '—'}"
                 for r in rows]
        return ToolResult.ok(data={"count": len(rows)}, message="\n".join(lines))


class CommProcessTool(Tool):
    name = "comm_process"
    description = ("Run one inbound communication item through the full "
                   "autonomy pipeline: dedupe → classify → conversation state "
                   "→ firewall → draft → evidence gate → send/park/pause. "
                   "Parameters describe the inbound message. Sending still "
                   "requires the normal authorization ladder — this tool "
                   "never bypasses policy.")
    parameters = {"platform": "email|telegram|phone|social",
                  "sender": "who sent it", "content": "message text",
                  "conversation_id": "optional thread id",
                  "account": "optional account"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms.autopilot import process_inbound
        from comms.models import UnifiedMessage
        import time as _time
        p = parameters or {}
        platform = str(p.get("platform", "")).strip()
        sender = str(p.get("sender", "")).strip()
        content = str(p.get("content", "")).strip()
        if not (platform and sender and content):
            return ToolResult.fail("missing_parameter",
                                   "platform + sender + content are required")
        msg = UnifiedMessage(platform=platform, account=str(p.get("account", "")),
                             sender=sender, content=content,
                             conversation_id=str(p.get("conversation_id", "")),
                             timestamp=_time.time())
        out = process_inbound(msg)
        return ToolResult.ok(data=out,
                             message=f"{out.get('outcome')} (event {out.get('event', '')[:12]})"
                                     + (f" — draft {out['draft']}" if out.get("draft") else ""))


class CommAutonomyTool(Tool):
    name = "comm_autonomy"
    description = ("Show autonomy state: pause/estop, per-platform shadow mode, "
                   "forced downgrade (quality gates), reply quality metrics.")
    parameters = {"platform": "optional platform filter"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import overrides, quality, store
        from comms.registry import connectors
        want = str((parameters or {}).get("platform", "")).strip()
        platforms = sorted({*connectors.health().keys()} |
                           {r["platform"] for r in store.db().query(
                               "SELECT DISTINCT platform FROM comm_quality")})
        lines = [f"overrides: paused={overrides.is_paused()} estop={overrides.is_estopped()}"]
        for p in platforms:
            if want and p != want:
                continue
            fm = quality.forced_max(p)
            m = quality.metrics(p)
            lines.append(
                f"- {p}: shadow={quality.shadow_state(p)} "
                f"forced_max={fm.get('forced_max_level', '—')} "
                f"accept={m.get('reply_acceptance_rate', '—')} "
                f"corrections={m.get('user_correction_rate', '—')} "
                f"fail_rate={m.get('failed_send_rate', '—')}")
        if len(lines) == 1:
            lines.append("(no connectors/telemetry yet)")
        return ToolResult.ok(message="\n".join(lines))
