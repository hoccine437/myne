# tools/device_state_tool.py
"""Device-state tool: the Core's one-call answer to 'what am I running on?'.

All probing lives in phone.device; this is just the Tool Manager adapter,
keeping the discovery/execution path identical to every other tool.
Non-destructive, read-only.
"""

from phone.device import probe_device, summary
from tools.base import Tool, ToolResult


class DeviceStateTool(Tool):
    name = "device_state"
    description = ("Describe the device Zerion is running on: OS/architecture, "
                   "mobile or desktop, screen, RAM, storage, battery, network, "
                   "and microphone/speaker/camera/touch availability.")
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        try:
            profile = probe_device()
        except Exception as e:
            return ToolResult.fail(error="probe_failed", message=str(e))
        return ToolResult.ok(data=profile, message=summary(profile))
