# Mark-X Lite Tool System

The Tool System lets the LLM autonomously choose and execute actions —
checking the time, doing math, reading/writing files, running code,
making HTTP requests, reading system info — instead of only replying
with text.

## How it works

1. `llm.py` asks `tools/manager.py` for the list of currently available
   tools and appends their names/descriptions/parameters to the prompt
   sent to the LLM (as additional context — `prompt.txt` itself is never
   modified).
2. The LLM decides whether a tool is needed and, if so, returns the
   tool's name as `intent` and any needed values as `parameters` — using
   the exact same JSON contract it already uses for everything else.
3. `main.py` looks up that `intent` in the Tool Manager. If a tool with
   that name exists, the manager runs it (or, for destructive tools,
   asks the user to confirm first) and speaks/prints the result.
4. If no tool matches the intent, Mark-X Lite falls back to the model's
   own text response — nothing breaks if the LLM doesn't ask for a tool.

No intent-to-tool mapping is hardcoded anywhere; a tool is available the
moment its file exists in `tools/`.

## Adding a new tool

Create one new file in `tools/`, e.g. `tools/weather.py`:

```python
from tools.base import Tool, ToolResult

class WeatherTool(Tool):
    name = "get_weather"
    description = "Get the current weather for a city."
    parameters = {"city": "the city name"}
    destructive = False  # True only for irreversible actions

    def available(self) -> bool:
        # Return False if this tool can't run right now (e.g. missing
        # API key, wrong platform). Never raise here.
        return True

    def execute(self, parameters: dict) -> ToolResult:
        city = parameters.get("city", "")
        if not city:
            return ToolResult.fail(error="missing_parameter", message="No city given.")
        # ... do the work ...
        return ToolResult.ok(data={"temp_c": 21}, message="21°C and clear in " + city)
```

That's it — no registration step. The registry (`tools/registry.py`)
scans every `.py` file in `tools/` and picks up any `Tool` subclass it
finds automatically, the next time the assistant starts.

### Rules for every tool

- `name` must be unique, short, snake_case — this is literally what the
  LLM writes into `intent` to call your tool.
- `available()` must never raise. If in doubt, return `False`.
- `execute()` must never raise. Catch everything internally and return
  `ToolResult.fail(error=..., message=...)`.
- Always return a `ToolResult` — `ToolResult.ok(data=..., message=...)`
  on success, `ToolResult.fail(...)` on failure. `message` is what gets
  spoken/printed to the user; `data` is the structured value for
  programmatic use.
- Set `destructive = True` if the tool does something irreversible
  (deletes, overwrites, moves files; runs shell/Python code). The Tool
  Manager will require the user to type `confirm` before it actually
  runs — you don't need to build that logic yourself.

## Tool API reference

### `tools/base.py`

- **`Tool`** — abstract base class. Subclass this for every tool.
  - `name: str` — unique identifier
  - `description: str` — shown to the LLM
  - `parameters: dict` — `{param_name: description}`, or `{}` if none
  - `destructive: bool` — default `False`
  - `available(self) -> bool` — environment/permission check
  - `execute(self, parameters: dict) -> ToolResult` — do the work
- **`ToolResult`** — structured result every tool returns.
  - `ToolResult.ok(data=None, message="")`
  - `ToolResult.fail(error="", message="")`
  - `ToolResult.needs_confirmation(message, data=None)` — used internally
    by the manager for destructive tools; you don't need to call this
    yourself, just set `destructive = True`.

### `tools/registry.py`

- `discover() -> dict` — returns `{tool_name: tool_instance}` for every
  valid tool found in `tools/`. Cached after first call.

### `tools/manager.py`

- `tool_manager` — the single shared `ToolManager` instance; import and
  use this directly.
  - `list_tools() -> list[dict]` — metadata for every currently
    *available* tool (already filtered by `available()`), for the LLM
    prompt.
  - `get_tool(name) -> Tool | None`
  - `execute(name, parameters) -> ToolResult`
  - `has_pending_confirmation() -> bool`
  - `confirm_pending() -> ToolResult`
  - `cancel_pending_confirmation() -> None`

## Included tools

| Category | Tools |
|---|---|
| Time/Date | `get_time`, `get_date` |
| Math/Random/ID | `calculate`, `random_number`, `generate_uuid` |
| Text/Encoding | `hash_text`, `base64_convert`, `format_json`, `text_stats` |
| Filesystem (safe) | `read_file`, `write_file`\*, `search_files`, `list_directory`, `create_folder` |
| Filesystem (destructive) | `move_file`, `copy_file`, `delete_file`, `rename_file` |
| Execution (destructive) | `run_python`, `run_shell` |
| Network | `http_get`, `http_post`, `download_file`\*, `get_env_var` |
| System info | `battery_status`, `storage_usage`, `memory_usage`, `cpu_info`, `network_info`, `process_list`, `system_info` |
| Device | `clipboard`, `open_url` |

\* `write_file` and `download_file` are marked destructive since they can
silently overwrite an existing file.

`process_list` and `battery_status` degrade gracefully when their
backend (`psutil`, or `termux-api` on Android) isn't installed — they
report unavailable rather than crashing.

## Security notes

- `run_python` and `run_shell` are always destructive, regardless of
  what the LLM's framing suggests — they require confirmation every
  time, are time-limited (15s), and have output capped at 4000 characters.
- File tools resolve paths with the permissions of whoever runs
  `main.py` — there's no sandbox. Treat Mark-X Lite like any other
  terminal tool with your user's file access.
- `get_env_var` refuses to read any variable whose name contains
  "key", "token", "secret", "password", or "credential".
- `download_file` is capped at 20MB and marked destructive.
