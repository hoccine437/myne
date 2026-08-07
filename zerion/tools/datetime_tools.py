# tools/datetime_tools.py
"""Time and date tools. Stdlib only, always available."""

from datetime import datetime

from tools.base import Tool, ToolResult


class GetTimeTool(Tool):
    name = "get_time"
    description = "Get the current local time."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        now = datetime.now().strftime("%H:%M:%S")
        return ToolResult.ok(data=now, message=f"The current time is {now}.")


class GetDateTool(Tool):
    name = "get_date"
    description = "Get today's date."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        today = datetime.now().strftime("%A, %B %d, %Y")
        return ToolResult.ok(data=today, message=f"Today is {today}.")
