# tools/device_tools.py
"""
Device-interaction tools: clipboard and URL opening. Both are strongly
platform-dependent, so each checks for the right backend and reports a
clear "not supported here" instead of failing silently or crashing.
"""

import shutil
import subprocess
import webbrowser

from tools.base import Tool, ToolResult
from tools.system_tools import _is_termux


class ClipboardTool(Tool):
    name = "clipboard"
    description = "Read or write the system clipboard."
    parameters = {"mode": "'read' or 'write'", "text": "text to write (required if mode is 'write')"}

    def available(self) -> bool:
        if _is_termux():
            return shutil.which("termux-clipboard-get") is not None
        return shutil.which("xclip") is not None or shutil.which("pbcopy") is not None

    def execute(self, parameters: dict) -> ToolResult:
        mode = str(parameters.get("mode", "read")).lower()
        if mode not in ("read", "write"):
            return ToolResult.fail(error="invalid_parameter", message="mode must be 'read' or 'write'.")

        try:
            if _is_termux():
                if mode == "read":
                    result = subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, timeout=5)
                    return ToolResult.ok(data=result.stdout, message=result.stdout)
                text = str(parameters.get("text", ""))
                subprocess.run(["termux-clipboard-set"], input=text, text=True, timeout=5)
                return ToolResult.ok(data=text, message="Copied to clipboard.")

            if shutil.which("pbcopy"):  # macOS, unlikely on this project's targets but harmless
                if mode == "read":
                    result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
                    return ToolResult.ok(data=result.stdout, message=result.stdout)
                text = str(parameters.get("text", ""))
                subprocess.run(["pbcopy"], input=text, text=True, timeout=5)
                return ToolResult.ok(data=text, message="Copied to clipboard.")

            if shutil.which("xclip"):
                if mode == "read":
                    result = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                                             capture_output=True, text=True, timeout=5)
                    return ToolResult.ok(data=result.stdout, message=result.stdout)
                text = str(parameters.get("text", ""))
                subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, timeout=5)
                return ToolResult.ok(data=text, message="Copied to clipboard.")

            return ToolResult.fail(error="unsupported", message="No clipboard backend found.")
        except Exception as e:
            return ToolResult.fail(error="clipboard_failed", message=str(e))


class URLOpenerTool(Tool):
    name = "open_url"
    description = "Open a URL in the default browser."
    parameters = {"url": "the URL to open"}

    def available(self) -> bool:
        if _is_termux():
            return shutil.which("termux-open-url") is not None
        return True  # webbrowser module is stdlib; may still fail on a headless box

    def execute(self, parameters: dict) -> ToolResult:
        url = str(parameters.get("url", "")).strip()
        if not url:
            return ToolResult.fail(error="missing_parameter", message="No URL provided.")
        try:
            if _is_termux():
                subprocess.run(["termux-open-url", url], timeout=5)
            else:
                if not webbrowser.open(url):
                    return ToolResult.fail(error="open_failed", message="No browser available to open the URL.")
            return ToolResult.ok(data=url, message=f"Opened {url}.")
        except Exception as e:
            return ToolResult.fail(error="open_failed", message=str(e))
