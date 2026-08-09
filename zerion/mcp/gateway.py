# mcp/gateway.py
"""MCP Gateway — the controlled boundary between Zerion's intelligence and
external/local capabilities.

    CALLER (agent / workflow / pipeline)
      → resolve server + capability
      → PERMISSION GATE (Constitution policy + caller role rules)
      → TIMEOUT MANAGER (bounded wait — task dropped, never abandoned silently)
      → RETRY MANAGER (single bounded retry on transient signals only)
      → AUDIT LOGGER (every invocation — no secrets, structured)
      → ERROR TRANSLATOR (driver/tool errors → stable gateway codes)
      → RESULT NORMALIZER (GatewayResult)

Caller roles:
  "agent"   — read:kind capabilities only, destructive denied even if asked
  "pipeline"/"core"/"workflow" — policy follows the underlying systems
  (tool confirmations stay owned by tools/manager.py)

This is the transport-level boundary. The external MCP wire protocol
(network sockets / stdio) is deliberately NOT BUILT yet — the current
deployment is a single-process, Termux-safe host; the boundary is real and
verified, the transport stub is a documented-next-step, not a fake.
"""

from __future__ import annotations

import concurrent.futures
import time
import uuid
from dataclasses import dataclass, field

from comms import audit
from core import logging as log

_TRANSIENT_MARKERS = ("timeout", "timed out", "temporarily", "connection",
                      "rate limit", "429", "503", "502")

_EXPECTED_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="mcp")


@dataclass
class GatewayResult:
    ok: bool
    capability: str
    server: str = ""
    data: object = None
    error: str = ""
    code: str = ""               # stable machine code for the caller
    duration_ms: int = 0
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    retried: bool = False


class Gateway:
    def __init__(self):
        self._servers: dict[str, dict] = {}
        self._built = False

    # -- discovery / registry -------------------------------------------

    def discover(self) -> dict:
        """Rebuild the in-process server map. Idempotent (cached)."""
        if self._built:
            return self._servers
        import importlib
        import pkgutil
        import mcp.servers
        found = {}
        for _, name, _ in pkgutil.iter_modules(mcp.servers.__path__):
            if name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"mcp.servers.{name}")
                srv = getattr(module, "SERVER", None)
                if isinstance(srv, dict) and srv.get("name") and srv.get("capabilities"):
                    found[srv["name"]] = srv
            except Exception as e:
                log.warning(f"mcp server '{name}' failed to load: {e}")
        self._servers = found
        self._built = True
        return found

    def servers(self) -> dict:
        return self.discover()

    def capabilities(self) -> list:
        out = []
        for srv_name, srv in self.discover().items():
            for cap, spec in srv["capabilities"].items():
                out.append({"capability": cap, "server": srv_name,
                            "kind": spec.get("kind", "read"),
                            "timeout_s": spec.get("timeout_s")})
        return out

    def health(self) -> dict:
        """Server registry liveness (in-process servers are loaded-on-
        discovery; probe = registry load + capability count)."""
        try:
            servers = self.servers()
            caps = sum(len(s["capabilities"]) for s in servers.values())
            return {"state": "healthy", "servers": sorted(servers),
                    "capabilities": caps}
        except Exception as e:
            return {"state": "failed", "error": str(e)[:200]}

    def capabilities_for_tool(self, tool_name: str) -> str | None:
        """Reverse map: raw tool name → gateway capability (adapters that
        wrap the tool declare 'tool': name). None = tool not on the agent
        boundary (callers then use the direct Tool Manager path)."""
        for srv in self.servers().values():
            for cap, spec in srv["capabilities"].items():
                if spec.get("tool") == tool_name:
                    return cap
        return None

    def call_tool(self, tool_name: str, parameters: dict | None = None,
                  *, caller: str = "pipeline", agent_type: str = "") -> GatewayResult:
        cap = self.capabilities_for_tool(tool_name)
        if cap is None:
            return GatewayResult(ok=False, capability=tool_name,
                                 code="mcp.capability_not_exposed",
                                 error=f"tool '{tool_name}' is not exposed through the "
                                       f"MCP gateway (boundary enforcement)")
        return self.call(cap, parameters or {}, caller=caller)

    def resolve(self, capability: str) -> tuple:
        for srv_name, srv in self.servers().items():
            spec = srv["capabilities"].get(capability)
            if spec is not None:
                return srv_name, srv, spec
        return None, None, None

    # -- the gate ---------------------------------------------------------

    def call(self, capability: str, parameters: dict | None = None,
             *, caller: str = "pipeline") -> GatewayResult:
        started = time.time()
        srv_name, srv, spec = self.resolve(capability)
        if spec is None:
            return self._finish(GatewayResult(
                ok=False, capability=capability, code="mcp.unknown_capability",
                error=f"no server exposes '{capability}'"), started, caller)

        # permission gate: the constitutional policy engine is the authority;
        # agents are additionally read-only by role
        from constitution.policy import Constitution
        kind = spec.get("kind", "read")
        action = {"read": "retrieve", "write": "modify",
                  "exec": "execute_shell"}.get(kind, "retrieve")
        decision = Constitution().evaluate(action)
        if not decision.allowed:
            return self._finish(GatewayResult(
                ok=False, capability=capability, server=srv_name,
                code="mcp.policy_denied", error=decision.reason), started, caller)
        if caller == "agent" and kind != "read":
            return self._finish(GatewayResult(
                ok=False, capability=capability, server=srv_name,
                code="mcp.agent_read_only",
                error="agents may only call read-kind capabilities; "
                      "the write/exec path stays supervised"), started, caller)

        handler = spec["handler"]
        timeout_s = max(1.0, float(spec.get("timeout_s", 10)))
        retries = 1 if spec.get("retry") == "transient" else 0
        attempt = 0
        last_err = ""
        retried = False
        while True:
            result = self._execute_timed(handler, parameters or {}, timeout_s)
            if result["ok"]:
                return self._finish(GatewayResult(
                    ok=True, capability=capability, server=srv_name,
                    data=result["result"].get("data"),
                    duration_ms=int((time.time() - started) * 1000),
                    retried=retried), started, caller)
            last_err = str(result.get("error") or "handler failed")
            if (attempt >= retries) or not self._is_transient(last_err):
                return self._finish(GatewayResult(
                    ok=False, capability=capability, server=srv_name,
                    code=self._translate(last_err),
                    error=last_err,
                    duration_ms=int((time.time() - started) * 1000),
                    retried=retried), started, caller)
            attempt += 1
            retried = True
            time.sleep(0.2)  # single short backoff (no unbounded loops)

    def _execute_timed(self, handler, parameters: dict, timeout_s: float) -> dict:
        """Run the handler bounded; in-process threads can't be killed, so a
        timeout reports and the thread is left daemonized (bounded by the
        handler's own timeouts — all adapters here are short and local)."""
        future = _EXPECTED_POOL.submit(handler, parameters)
        try:
            result = future.result(timeout=timeout_s)
            if isinstance(result, dict) and result.get("success") is not None:
                return {"ok": bool(result["success"]),
                        "result": result, "error": result.get("error")}
            return {"ok": False, "error": "handler returned an invalid envelope"}
        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": f"timeout after {timeout_s}s"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _is_transient(self, err: str) -> bool:
        low = err.lower()
        return any(m in low for m in _TRANSIENT_MARKERS)

    def _translate(self, err: str) -> str:
        low = err.lower()
        if "timeout" in low or "timed out" in low:
            return "mcp.timeout"
        if "permission" in low or "denied" in low or "constitution" in low:
            return "mcp.denied"
        if "not found" in low or "no such" in low:
            return "mcp.not_found"
        return "mcp.error"

    def _finish(self, result: GatewayResult, started: float, caller: str) -> GatewayResult:
        if not result.duration_ms:
            result.duration_ms = int((time.time() - started) * 1000)
        audit.record("mcp.call", platform="mcp", target=result.capability,
                     result="ok" if result.ok else result.code or "error",
                     error="" if result.ok else result.error,
                     extra={"server": result.server, "caller": caller,
                            "ms": result.duration_ms, "retried": result.retried,
                            "call_id": result.call_id})
        return result


gateway = Gateway()
