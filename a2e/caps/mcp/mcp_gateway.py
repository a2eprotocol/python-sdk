"""
a2e/mcp_gateway.py — MCP Server Gateway

The gateway manages connections to one or more MCP servers and presents their
capabilities through the A2E interface:

  • MCP tools      → added to the ToolRegistry with source="mcp"
  • MCP resources  → accessible via MCPResourceListRequest / MCPResourceReadRequest
  • MCP prompts    → accessible via MCPPromptListRequest / MCPPromptGetRequest
  • Notifications  → forwarded to the agent as MCPServerPush events
  • Sampling       → MCPSamplingRequest forwarded to agent for LLM execution

Two transports are supported:
  StdioMCPConnection   — spawn a subprocess, speak JSON-RPC over stdin/stdout
  SSEMCPConnection     — connect to an HTTP+SSE endpoint

Both transports implement MCPConnection (abstract base).

MCP protocol overview (JSON-RPC 2.0):
  Client → Server: initialize, tools/list, tools/call, resources/list,
                    resources/read, resources/subscribe, prompts/list,
                    prompts/get, ping, roots/list (response)
  Server → Client: initialize (response), notifications/*, sampling/createMessage
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
import uuid
from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict
from typing import Any, Callable, Union, Awaitable

from a2e.caps.mcp.protocol import (
    MCPServerConfig,
    MCPServerInfo,
    MCPServerStatus,
    MCPTransport,
    MCPResource,
    MCPResourceContent,
    MCPResourceReadResponse,
    MCPPrompt,
    MCPPromptGetResponse,
    MCPSamplingRequest,
    MCPSamplingResponse,
    MCPRootsListRequest,
    MCPServerPush,
    MCPErrorCode,
)

from a2e.caps.tools.protocol import (
    ToolDefinition,
    ToolResult
)


# Runner can be sync or async
ToolRunner = Union[
    Callable[..., Any],
    Callable[..., Awaitable[Any]],
]
EmitFn = Callable[[str, Any], None]


class ToolEntry(BaseModel):
    """
    Runtime registry entry for a tool.

    - definition → static tool metadata/schema
    - runner     → execution function bound to a connection/server
    """

    definition: ToolDefinition
    runner: ToolRunner

    # 🔥 Required to allow function/callable
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Optional helper
    def run(self, **kwargs):
        return self.runner(**kwargs)


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# JSON-RPC 2.0 helpers
# ─────────────────────────────────────────────────────────────────────────────
def _rpc_request(method: str, params: dict | None = None, req_id: str = "") -> str:
    msg = {
        "jsonrpc": "2.0",
        "id": req_id or uuid.uuid4().hex[:8],
        "method": method,
    }
    if params:
        msg["params"] = params
    return json.dumps(msg, separators=(",", ":"))


def _rpc_notification(method: str, params: dict | None = None) -> str:
    msg = {"jsonrpc": "2.0", "method": method}
    if params:
        msg["params"] = params
    return json.dumps(msg, separators=(",", ":"))


def _rpc_response(req_id: str, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result},
                      separators=(",", ":"), default=str)


def _rpc_error_resp(req_id: str, code: int, message: str) -> str:
    return json.dumps({
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": code, "message": message},
    }, separators=(",", ":"))


# ─────────────────────────────────────────────────────────────────────────────
# MCP client capabilities (what this A2E client supports)
# ─────────────────────────────────────────────────────────────────────────────

MCP_CLIENT_INFO = {
    "name": "a2e-mcp-bridge",
    "version": "1.0.0",
}

MCP_CLIENT_CAPABILITIES = {
    "roots": {"listChanged": True},
    "sampling": {},
}


# ═════════════════════════════════════════════════════════════════════════════
# Abstract MCP connection
# ═════════════════════════════════════════════════════════════════════════════

class MCPConnection(ABC):
    """
    Abstract base for a connection to one MCP server.
    Subclasses implement the stdio and SSE transports.
    """

    def __init__(
        self,
        config: MCPServerConfig,
        on_push: Callable[[MCPServerPush], None],
        on_sampling: Callable[[MCPSamplingRequest], None],
        on_roots_req: Callable[[MCPRootsListRequest], None],
    ):
        self.config = config
        self._on_push = on_push
        self._on_sampling = on_sampling
        self._on_roots_req = on_roots_req

        self._pending: dict[str, queue.Queue] = {}
        self._info: MCPServerInfo = MCPServerInfo(
            server_id=config.server_id,
            name=config.name,
            transport=config.transport,
        )
        self._lock = threading.Lock()
        self._tools: list[dict] = []
        self._resources: list[dict] = []
        self._prompts: list[dict] = []

    @property
    def info(self) -> MCPServerInfo:
        return self._info

    @abstractmethod
    def connect(self): ...

    @abstractmethod
    def disconnect(self): ...

    @abstractmethod
    def _send_line(self, line: str): ...

    def call(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 30.0
    ) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        req_id = uuid.uuid4().hex[:8]
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._pending[req_id] = q
        self._send_line(_rpc_request(method, params, req_id))

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    self._pending.pop(req_id, None)
                raise TimeoutError(
                    f"MCP call '{method}' timed out after {timeout}s"
                )
            try:
                result = q.get(timeout=min(remaining, 1.0))
                return result
            except queue.Empty:
                continue

    def notify(self, method: str, params: dict | None = None):
        """Send a JSON-RPC notification (no response expected)."""
        self._send_line(_rpc_notification(method, params))

    def respond(self, req_id: str, result: Any):
        """Send a JSON-RPC response (for server-initiated requests)."""
        self._send_line(_rpc_response(req_id, result))

    def respond_error(self, req_id: str, code: int, message: str):
        self._send_line(_rpc_error_resp(req_id, code, message))

    def _dispatch_line(self, raw: str):
        """Called by the read loop for each line received from the MCP server."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        if "id" in msg and ("result" in msg or "error" in msg):
            # Response to one of our requests
            req_id = str(msg["id"])
            with self._lock:
                q = self._pending.pop(req_id, None)
            if q:
                if "error" in msg:
                    q.put(MCPRemoteError(msg["error"]))
                else:
                    q.put(msg.get("result"))
            return

        method = msg.get("method", "")

        if "id" in msg and method:
            # Server-initiated request (sampling, roots)
            srv_id = str(msg["id"])
            params = msg.get("params", {})
            if method == "sampling/createMessage":
                self._handle_sampling_request(srv_id, params)
            elif method == "roots/list":
                self._handle_roots_request(srv_id)
            else:
                # Unknown server request — return method not found
                self.respond_error(srv_id, -32601, f"Method not found: {method}")
            return

        if method:
            # Notification (no id)
            params = msg.get("params", {})
            push = MCPServerPush(
                server_id=self.config.server_id,
                method=method,
                params=params,
            )
            try:
                self._on_push(push)
            except Exception:
                pass

            # Refresh cached tool/resource/prompt lists on list_changed notifications
            if method in ("notifications/tools/list_changed",):
                threading.Thread(target=self._refresh_tools, daemon=True).start()
            elif method in ("notifications/resources/list_changed",):
                threading.Thread(target=self._refresh_resources, daemon=True).start()
            elif method in ("notifications/prompts/list_changed",):
                threading.Thread(target=self._refresh_prompts, daemon=True).start()

    def _handle_sampling_request(self, srv_id: str, params: dict):
        req = MCPSamplingRequest(
            server_id=self.config.server_id,
            mcp_request_id=srv_id,
            messages=params.get("messages", []),
            model_preferences=params.get("modelPreferences", {}),
            system_prompt=params.get("systemPrompt", ""),
            include_context=params.get("includeContext", "none"),
            temperature=params.get("temperature", 1.0),
            max_tokens=params.get("maxTokens", 1024),
            stop_sequences=params.get("stopSequences", []),
            metadata=params.get("metadata", {}),
        )
        try:
            self._on_sampling(req)
        except Exception:
            self.respond_error(srv_id, -32000, "Sampling not available")

    def _handle_roots_request(self, srv_id: str):
        req = MCPRootsListRequest(
            server_id=self.config.server_id,
            mcp_request_id=srv_id,
        )
        try:
            self._on_roots_req(req)
        except Exception:
            self.respond(srv_id, {"roots": []})

    # ── Initialization ────────────────────────────────────────────────────

    def _do_initialize(self):
        """Perform the MCP initialize handshake after transport is open."""
        result = self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": MCP_CLIENT_CAPABILITIES,
            "clientInfo": MCP_CLIENT_INFO,
        }, timeout=self.config.timeout)

        if isinstance(result, MCPRemoteError):
            raise ConnectionError(f"MCP initialize failed: {result}")

        self._info.mcp_version = result.get("protocolVersion", "")
        srv_info = result.get("serverInfo", {})
        self._info.server_name = srv_info.get("name", "")
        self._info.server_version = srv_info.get("version", "")
        self._info.status = MCPServerStatus.READY.value
        self._info.connected_at = time.time()

        # Send initialized notification
        self.notify("notifications/initialized")

        # Cache capabilities
        self._refresh_tools()
        self._refresh_resources()
        self._refresh_prompts()

    def _refresh_tools(self):
        try:
            result = self.call("tools/list", timeout=self.config.timeout)
            if not isinstance(result, MCPRemoteError):
                self._tools = result.get("tools", [])
                self._info.tools_count = len(self._tools)
        except Exception as e:
            logger.warning(f"[mcp:{self.config.server_id}] tools/list failed: {e}")

    def _refresh_resources(self):
        try:
            result = self.call("resources/list", timeout=self.config.timeout)
            if not isinstance(result, MCPRemoteError):
                self._resources = result.get("resources", [])
                self._info.resources_count = len(self._resources)
        except Exception as e:
            logger.warning(f"[mcp:{self.config.server_id}] resources/list failed: {e}")

    def _refresh_prompts(self):
        try:
            result = self.call("prompts/list", timeout=self.config.timeout)
            if not isinstance(result, MCPRemoteError):
                self._prompts = result.get("prompts", [])
                self._info.prompts_count = len(self._prompts)
        except Exception as e:
            logger.warning(f"[mcp:{self.config.server_id}] prompts/list failed: {e}")

    # ── Public data accessors ─────────────────────────────────────────────

    def get_tools(self) -> list[dict]:
        return list(self._tools)

    def get_resources(self) -> list[dict]:
        return list(self._resources)

    def get_prompts(self) -> list[dict]:
        return list(self._prompts)

    def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        emit: EmitFn = lambda k, d: None
    ) -> ToolResult:
        """Invoke an MCP tool and return a ToolResult."""
        emit(
            "status",
            {
                "message": f"[mcp:{self.config.name}] {tool_name}"
            }
        )
        t0 = time.monotonic()
        try:
            result = self.call("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            }, timeout=self.config.timeout)
        except TimeoutError as e:
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
                error_code=MCPErrorCode.MCP_SERVER_UNAVAILABLE.value
            )

        if isinstance(result, MCPRemoteError):
            return ToolResult(
                success=False, output=None,
                error=result.message,
                error_code=(
                    MCPErrorCode.MCP_TOOL_NOT_FOUND.value
                    if result.code == -32602
                    else MCPErrorCode.MCP_PROTOCOL_ERROR.value
                ),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        # MCP tool result: { content: [...], isError: bool }
        is_error = result.get("isError", False)
        content = result.get("content", [])

        # Flatten text content blocks into a single output dict
        text_parts = [c["text"] for c in content if c.get("type") == "text" and "text" in c]
        image_parts = [c for c in content if c.get("type") == "image"]

        output: dict = {"content": content, "text": "\n".join(text_parts)}
        if image_parts:
            output["images"] = image_parts

        emit(
            "status",
            {
                "message": "done" if not is_error else "error"
            }
        )
        return ToolResult(
            success=not is_error,
            output=output,
            error=output["text"] if is_error else None,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    def read_resource(self, uri: str) -> MCPResourceReadResponse:
        try:
            result = self.call("resources/read", {"uri": uri},
                               timeout=self.config.timeout)
        except Exception as e:
            return MCPResourceReadResponse(
                server_id=self.config.server_id,
                error=str(e)
            )

        if isinstance(result, MCPRemoteError):
            return MCPResourceReadResponse(
                server_id=self.config.server_id,
                error=result.message
            )

        raw_contents = result.get("contents", [])
        contents = []
        for c in raw_contents:
            if "text" in c:
                contents.append(
                    MCPResourceContent(
                        uri=c.get("uri", uri),
                        mime_type=c.get("mimeType", "text/plain"),
                        text=c["text"],
                        type="text"
                    ).model_dump()
                )
            elif "blob" in c:
                contents.append(
                    MCPResourceContent(
                        uri=c.get("uri", uri),
                        mime_type=c.get("mimeType", "application/octet-stream"),
                        blob=c["blob"],
                        type="blob"
                    ).model_dump()
                )
        return MCPResourceReadResponse(server_id=self.config.server_id, contents=contents)

    def get_prompt(self, name: str, arguments: dict) -> MCPPromptGetResponse:
        try:
            result = self.call(
                "prompts/get",
                {"name": name, "arguments": arguments},
                timeout=self.config.timeout
            )
        except Exception as e:
            return MCPPromptGetResponse(
                server_id=self.config.server_id,
                error=str(e)
            )

        if isinstance(result, MCPRemoteError):
            return MCPPromptGetResponse(
                server_id=self.config.server_id,
                error=result.message
            )

        messages = result.get("messages", [])
        return MCPPromptGetResponse(
            server_id=self.config.server_id,
            description=result.get("description", ""),
            messages=messages,
        )

    def subscribe_resource(self, uri: str) -> bool:
        try:
            result = self.call("resources/subscribe", {"uri": uri},
                               timeout=self.config.timeout)
            return not isinstance(result, MCPRemoteError)
        except Exception:
            return False

    def ping(self) -> float:
        t0 = time.monotonic()
        try:
            self.call("ping", timeout=5.0)
            return (time.monotonic() - t0) * 1000
        except Exception:
            return -1.0


# ─────────────────────────────────────────────────────────────────────────────
# MCPRemoteError — wraps a JSON-RPC error object
# ─────────────────────────────────────────────────────────────────────────────

class MCPRemoteError(Exception):
    def __init__(self, error_dict: dict):
        self.code = error_dict.get("code", -1)
        self.message = error_dict.get("message", "unknown error")
        self.data = error_dict.get("data")
        super().__init__(self.message)


# ═════════════════════════════════════════════════════════════════════════════
# Stdio transport
# ═════════════════════════════════════════════════════════════════════════════

class StdioMCPConnection(MCPConnection):
    """
    Communicates with an MCP server that runs as a child subprocess.
    Messages are exchanged over the child's stdin/stdout as NDJSON.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None

    def connect(self):
        cfg = self.config
        import os as _os
        env = {**_os.environ, **cfg.env}
        self._proc = subprocess.Popen(
            cfg.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cfg.cwd or None,
            env=env,
            text=True,
            bufsize=1,
        )
        self._info.status = MCPServerStatus.CONNECTING.value
        logger.info(f"[mcp-stdio:{cfg.server_id}] Started pid={self._proc.pid}")

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        try:
            self._do_initialize()
        except Exception as e:
            self._info.status = MCPServerStatus.ERROR.value
            self._info.error = str(e)
            raise

    def disconnect(self):
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._info.status = MCPServerStatus.DISCONNECTED.value

    def _send_line(self, line: str):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(line + "\n")
                self._proc.stdin.flush()
            except Exception as e:
                logger.warning(f"[mcp-stdio:{self.config.server_id}] send failed: {e}")

    def _read_loop(self):
        for raw in self._proc.stdout:
            raw = raw.strip()
            if raw:
                self._dispatch_line(raw)
        # process exited
        self._info.status = MCPServerStatus.DISCONNECTED.value
        if self.config.auto_reconnect:
            logger.info(f"[mcp-stdio:{self.config.server_id}] Disconnected; will reconnect")


# ═════════════════════════════════════════════════════════════════════════════
# SSE transport
# ═════════════════════════════════════════════════════════════════════════════

class SSEMCPConnection(MCPConnection):
    """
    Communicates with an MCP server over HTTP + Server-Sent Events.

    Uses only the standard library (urllib) for the SSE receive stream.
    POST requests carry JSON-RPC messages to the server's /message endpoint.
    SSE events carry responses and notifications from the server.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._post_url: str = ""
        self._sse_thread: threading.Thread | None = None
        self._session_id: str = ""

    def connect(self):

        cfg = self.config
        self._info.status = MCPServerStatus.CONNECTING.value

        # Connect to SSE endpoint; first event contains the session endpoint URL
        self._sse_thread = threading.Thread(
            target=self._sse_loop, daemon=True,
            args=(cfg.url, cfg.headers)
        )
        self._sse_thread.start()

        # Wait for the endpoint event
        deadline = time.monotonic() + cfg.timeout
        while not self._post_url:
            if time.monotonic() > deadline:
                raise TimeoutError("MCP SSE: timed out waiting for endpoint event")
            time.sleep(0.1)

        try:
            self._do_initialize()
        except Exception as e:
            self._info.status = MCPServerStatus.ERROR.value
            self._info.error = str(e)
            raise

    def disconnect(self):
        self._info.status = MCPServerStatus.DISCONNECTED.value
        # The SSE read loop will exit naturally when the connection drops

    def _send_line(self, line: str):
        if not self._post_url:
            return
        import urllib.request
        data = line.encode("utf-8")
        req = urllib.request.Request(
            self._post_url, data=data,
            headers={
                **self.config.headers,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout):
                pass
        except Exception as e:
            logger.warning(f"[mcp-sse:{self.config.server_id}] POST failed: {e}")

    def _sse_loop(self, url: str, extra_headers: dict):
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={
                **extra_headers,
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
            }
        )
        try:
            with urllib.request.urlopen(req) as resp:
                event_type = ""
                data_lines: list[str] = []
                for raw_line in resp:
                    line = raw_line.decode("utf-8").rstrip("\n")
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif line == "":
                        data = "\n".join(data_lines)
                        if event_type == "endpoint":
                            base = url.rsplit("/", 1)[0]
                            self._post_url = base + "/" + data.lstrip("/")
                        elif data:
                            self._dispatch_line(data)
                        event_type = ""
                        data_lines = []
        except Exception as e:
            logger.warning(f"[mcp-sse:{self.config.server_id}] SSE loop error: {e}")
            self._info.status = MCPServerStatus.DISCONNECTED.value


# ═════════════════════════════════════════════════════════════════════════════
# MCPGateway — manages all MCP server connections
# ═════════════════════════════════════════════════════════════════════════════

class MCPGateway:
    """
    Manages multiple MCP server connections on behalf of the A2E host.

    Responsibilities:
      • Register / unregister MCP servers
      • Maintain connection pool (StdioMCPConnection / SSEMCPConnection)
      • Aggregate tools, resources, prompts from all servers
      • Route tool/call/req for MCP tools to the right server
      • Forward MCP notifications as MCPServerPush to the agent
      • Forward MCP sampling requests to the agent's LLM
      • Respond to MCP roots requests from the agent
    """

    def __init__(
        self,
        tool_registry,   # a2e.tools.ToolRegistry
        send_fn: Callable,   # (A2EMessage) → None — sends to agent
        sampling_fn: Callable | None = None,  # (MCPSamplingRequest) → MCPSamplingResponse
        roots: list[dict] | None = None,
    ):
        self._registry = tool_registry
        self._send = send_fn
        self._sampling_fn = sampling_fn
        self._roots = roots or []
        self._connections: dict[str, MCPConnection] = {}
        self._lock = threading.Lock()

    # ── Server lifecycle ──────────────────────────────────────────────────
    def register(self, config: MCPServerConfig) -> MCPServerInfo:
        """Connect to a new MCP server and expose its tools/resources."""
        if config.transport == MCPTransport.SSE.value:
            conn = SSEMCPConnection(
                config, self._on_push, self._on_sampling, self._on_roots_req
            )
        else:
            conn = StdioMCPConnection(
                config, self._on_push, self._on_sampling, self._on_roots_req
            )

        conn.connect()

        with self._lock:
            self._connections[config.server_id] = conn

        # Inject MCP tools into the ToolRegistry
        self._sync_tools(conn)
        logger.info(f"[mcp-gw] Registered server '{config.name}' "
                    f"({conn.info.tools_count} tools, "
                    f"{conn.info.resources_count} resources)")
        return conn.info

    def unregister(self, server_id: str) -> bool:
        with self._lock:
            conn = self._connections.pop(server_id, None)
        if conn:
            # Remove this server's tools from the registry
            self._remove_tools(server_id)
            conn.disconnect()
            return True
        return False

    def list_servers(self, status_filter: str = "") -> list[MCPServerInfo]:
        with self._lock:
            conns = list(self._connections.values())
        infos = [c.info for c in conns]
        if status_filter:
            infos = [i for i in infos if i.status == status_filter]
        return infos

    def get_connection(self, server_id: str) -> MCPConnection | None:
        with self._lock:
            return self._connections.get(server_id)

    # ── Aggregated resource / prompt access ──────────────────────────────

    def list_resources(
        self,
        server_id: str = "",
        cursor: str = ""
    ) -> tuple[list[MCPResource], str]:
        with self._lock:
            conns = ([self._connections[server_id]]
                     if server_id and server_id in self._connections
                     else list(self._connections.values()))
        resources = []
        for conn in conns:
            for r in conn.get_resources():
                if (not conn.config.resource_allow_list or
                        r.get("name") in conn.config.resource_allow_list):
                    resources.append(MCPResource(
                        uri=r.get("uri", ""),
                        name=r.get("name", ""),
                        description=r.get("description", ""),
                        mime_type=r.get("mimeType", ""),
                        server_id=conn.config.server_id,
                        annotations=r.get("annotations", {}),
                    ))
        return resources, ""  # no cursor pagination in this baseline

    def read_resource(self, uri: str, server_id: str = ""):
        conn = self._resolve_server(uri, server_id)
        if conn is None:
            return MCPResourceReadResponse(
                error=f"No MCP server found for URI: {uri}"
            )
        return conn.read_resource(uri)

    def subscribe_resource(self, uri: str, server_id: str = "") -> bool:
        conn = self._resolve_server(uri, server_id)
        return conn.subscribe_resource(uri) if conn else False

    def list_prompts(self, server_id: str = "") -> list[MCPPrompt]:
        with self._lock:
            conns = ([self._connections[server_id]]
                     if server_id and server_id in self._connections
                     else list(self._connections.values()))
        prompts = []
        for conn in conns:
            for p in conn.get_prompts():
                prompts.append(MCPPrompt(
                    name=p.get("name", ""),
                    description=p.get("description", ""),
                    server_id=conn.config.server_id,
                    arguments=p.get("arguments", []),
                ))
        return prompts

    def get_prompt(self, name: str, arguments: dict, server_id: str = ""):
        conn = self._find_prompt_server(name, server_id)
        if conn is None:
            from .protocol import MCPPromptGetResponse
            return MCPPromptGetResponse(error=f"Prompt '{name}' not found")
        return conn.get_prompt(name, arguments)

    # ── Tool sync ─────────────────────────────────────────────────────────
    def _sync_tools(self, conn: MCPConnection):
        """Register the connection's tools in the ToolRegistry as MCP-sourced tools."""
        for t in conn.get_tools():
            name = t.get("name", "")
            if not name:
                continue
            if conn.config.tool_allow_list and name not in conn.config.tool_allow_list:
                continue

            # Build a ToolDefinition with source metadata embedded in tags
            definition = ToolDefinition(
                name=f"{conn.config.server_id}__{name}",  # namespaced to avoid collisions
                description=f"[MCP:{conn.config.name}] {t.get('description', '')}",
                input_schema=t.get("inputSchema", {}),
                streaming=False,
                idempotent=False,
                tags=["mcp", conn.config.server_id, conn.config.name],
                version="1.0",
            )

            # Capture conn + name in closure
            def make_runner(c: MCPConnection, n: str):
                def runner(inp: dict, emit: EmitFn) -> ToolResult:
                    return c.call_tool(n, inp, emit)
                return runner

            entry = ToolEntry(definition=definition, runner=make_runner(conn, name))
            self._registry.register(entry)

    def _remove_tools(self, server_id: str):
        """Remove all tools belonging to a given server from the registry."""
        prefix = f"{server_id}__"
        for name in list(self._registry._tools.keys()):
            if name.startswith(prefix):
                del self._registry._tools[name]

    # ── Push / sampling / roots callbacks ────────────────────────────────

    def _on_push(self, push: MCPServerPush):
        self._send(push)
        # Re-sync tools if the tools list changed
        if push.method == "notifications/tools/list_changed":
            with self._lock:
                conn = self._connections.get(push.server_id)
            if conn:
                self._remove_tools(push.server_id)
                self._sync_tools(conn)

    def _on_sampling(self, req: MCPSamplingRequest):
        """Forward sampling request to the A2E agent via the send channel."""
        self._send(req)

    def _on_roots_req(self, req: MCPRootsListRequest):
        """Immediately respond with the configured roots list."""
        conn = self.get_connection(req.server_id)
        if conn:
            conn.respond(req.mcp_request_id, {"roots": self._roots})

    def handle_sampling_response(self, resp: MCPSamplingResponse):
        """Called by the host when the agent sends back a sampling response."""
        conn = self.get_connection(resp.server_id)
        if conn is None:
            return
        if resp.error:
            conn.respond_error(resp.mcp_request_id, -32000, resp.error)
        else:
            conn.respond(resp.mcp_request_id, {
                "role": resp.role,
                "content": resp.content,
                "model": resp.model,
                "stopReason": resp.stop_reason,
            })

    def handle_roots_response(self, resp):
        """Called by the host when the agent responds to a roots list request."""
        conn = self.get_connection(resp.server_id)
        if conn:
            conn.respond(resp.mcp_request_id, {"roots": resp.roots})

    # ── Helpers ───────────────────────────────────────────────────────────

    def _resolve_server(self, uri: str, hint: str = "") -> MCPConnection | None:
        if hint:
            return self._connections.get(hint)
        # Try to match by URI prefix from each server's resource list
        with self._lock:
            conns = list(self._connections.values())
        for conn in conns:
            for r in conn.get_resources():
                if r.get("uri") == uri or uri.startswith(r.get("uri", "")):
                    return conn
        return conns[0] if conns else None

    def _find_prompt_server(self, name: str, hint: str = "") -> MCPConnection | None:
        if hint:
            return self._connections.get(hint)
        with self._lock:
            conns = list(self._connections.values())
        for conn in conns:
            if any(p.get("name") == name for p in conn.get_prompts()):
                return conn
        return None

    def shutdown(self):
        with self._lock:
            server_ids = list(self._connections.keys())
        for sid in server_ids:
            self.unregister(sid)
