# tools/network_tools.py
"""
Network tools. Uses `requests`, already a required dependency for the LLM
API calls — no new packages needed. All requests are time-limited and
response size is capped to avoid hanging or exhausting memory on a huge
download. Downloading is marked destructive since it writes a file to
disk (can overwrite an existing one).
"""

import os

import requests

from tools.base import Tool, ToolResult

_TIMEOUT_SECONDS = 15
_MAX_RESPONSE_CHARS = 4000
_MAX_DOWNLOAD_BYTES = 20_000_000  # 20MB cap


class HTTPGetTool(Tool):
    name = "http_get"
    description = "Make an HTTP GET request to a URL and return the response body."
    parameters = {"url": "the URL to fetch"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        url = str(parameters.get("url", "")).strip()
        if not url:
            return ToolResult.fail(error="missing_parameter", message="No URL provided.")
        try:
            resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
            text = resp.text[:_MAX_RESPONSE_CHARS]
            return ToolResult.ok(
                data={"status_code": resp.status_code, "body": text},
                message=f"HTTP {resp.status_code}: {text[:200]}",
            )
        except Exception as e:
            return ToolResult.fail(error="request_failed", message=str(e))


class HTTPPostTool(Tool):
    name = "http_post"
    description = "Make an HTTP POST request with a JSON body and return the response."
    parameters = {"url": "the URL to post to", "body": "a JSON-serializable dict to send"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        url = str(parameters.get("url", "")).strip()
        body = parameters.get("body", {})
        if not url:
            return ToolResult.fail(error="missing_parameter", message="No URL provided.")
        try:
            resp = requests.post(url, json=body, timeout=_TIMEOUT_SECONDS)
            text = resp.text[:_MAX_RESPONSE_CHARS]
            return ToolResult.ok(
                data={"status_code": resp.status_code, "body": text},
                message=f"HTTP {resp.status_code}: {text[:200]}",
            )
        except Exception as e:
            return ToolResult.fail(error="request_failed", message=str(e))


class DownloadFileTool(Tool):
    name = "download_file"
    description = "Download a file from a URL to a local path."
    parameters = {"url": "URL to download from", "path": "local path to save to"}
    destructive = True  # can overwrite an existing file

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        url = str(parameters.get("url", "")).strip()
        path = str(parameters.get("path", "")).strip()
        if not url or not path:
            return ToolResult.fail(error="missing_parameter", message="Both url and path are required.")
        full = os.path.abspath(os.path.expanduser(path))
        try:
            with requests.get(url, timeout=_TIMEOUT_SECONDS, stream=True) as resp:
                resp.raise_for_status()
                written = 0
                os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
                with open(full, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        written += len(chunk)
                        if written > _MAX_DOWNLOAD_BYTES:
                            f.close()
                            os.remove(full)
                            return ToolResult.fail(error="too_large", message="Download exceeded the 20MB limit.")
                        f.write(chunk)
            return ToolResult.ok(data=full, message=f"Downloaded {written} bytes to {path}.")
        except Exception as e:
            return ToolResult.fail(error="download_failed", message=str(e))


class EnvironmentVariableTool(Tool):
    name = "get_env_var"
    description = "Read the value of an environment variable (name only, not secrets like API keys)."
    parameters = {"name": "environment variable name"}

    _BLOCKED_SUBSTRINGS = ("key", "token", "secret", "password", "credential")

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        name = str(parameters.get("name", "")).strip()
        if not name:
            return ToolResult.fail(error="missing_parameter", message="No variable name provided.")
        if any(s in name.lower() for s in self._BLOCKED_SUBSTRINGS):
            return ToolResult.fail(
                error="blocked",
                message="Refusing to read environment variables that look like secrets/API keys.",
            )
        value = os.environ.get(name)
        if value is None:
            return ToolResult.fail(error="not_set", message=f"'{name}' is not set.")
        return ToolResult.ok(data=value, message=f"{name}={value}")
