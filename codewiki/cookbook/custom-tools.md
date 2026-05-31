# Custom Tools Plugin & Client Example

```text
a2e/caps/tools/plugin.py  — ToolPlugin ABC
a2e/caps/tools/client.py   — ToolAPI
a2e/caps/tools/protocol.py — ToolDefinition, ToolParameter, ToolCall*, ToolResult, ToolEvent, ToolErrorCode
```

## Overview

Tools are the most fundamental capability in A2E — primitive, stateless operations like file I/O, HTTP requests, and code execution. This cookbook shows how to:

1. **Plugin side**: Write a custom `ToolPlugin` with manifest definition and execution logic, including streaming events
2. **Client side**: List tools, call tools, handle streaming events, and process results

## Plugin Side: HTTP Request Tool Plugin

Below is a complete tool plugin that provides an HTTP client (`http_get`, `http_post`):

```python
import json
import time
import urllib.request
import urllib.error
from typing import Callable

from a2e.core.plugins.interface import A2EPlugin
from a2e.caps.tools.protocol import (
    ToolDefinition, ToolParameter,
    ToolListRequest, ToolListResponse,
    ToolCallRequest, ToolCallResponse,
    ToolResult, ToolEvent,
)

class HTTPToolsPlugin(A2EPlugin):
    """Provides http_get and http_post as native A2E tools."""

    name = "http_tools"
    type = "tools"
    priority = 5

    def setup(self, host, config):
        super().setup(host, config)
        self._event_callback = None

        # Build tool manifests
        self._tools = [
            ToolDefinition(
                name="http_get",
                description="Send an HTTP GET request and return the response body",
                input_parameters=[
                    ToolParameter(
                        name="url",
                        type="string",
                        description="The URL to request",
                        required=True,
                    ),
                    ToolParameter(
                        name="headers",
                        type="object",
                        description="Optional request headers as key-value pairs",
                        required=False,
                    ),
                    ToolParameter(
                        name="timeout",
                        type="integer",
                        description="Request timeout in seconds",
                        required=False,
                    ),
                ],
                output_parameters=[
                    ToolParameter(
                        name="status_code",
                        type="integer",
                        description="HTTP status code",
                    ),
                    ToolParameter(
                        name="body",
                        type="string",
                        description="Response body",
                    ),
                ],
                streaming=True,
                idempotent=True,
                tags=["http", "network", "read"],
                version="1.0.0",
                toolkit=None,
            ),
            ToolDefinition(
                name="http_post",
                description="Send an HTTP POST request with a JSON body",
                input_parameters=[
                    ToolParameter(
                        name="url",
                        type="string",
                        description="The URL to post to",
                        required=True,
                    ),
                    ToolParameter(
                        name="body",
                        type="object",
                        description="JSON body to send",
                        required=True,
                    ),
                    ToolParameter(
                        name="headers",
                        type="object",
                        description="Optional request headers",
                        required=False,
                    ),
                    ToolParameter(
                        name="timeout",
                        type="integer",
                        description="Request timeout in seconds",
                        required=False,
                    ),
                ],
                output_parameters=[
                    ToolParameter(
                        name="status_code",
                        type="integer",
                        description="HTTP status code",
                    ),
                    ToolParameter(
                        name="body",
                        type="string",
                        description="Response body",
                    ),
                ],
                streaming=True,
                idempotent=False,
                tags=["http", "network", "write"],
                version="1.0.0",
                toolkit=None,
            ),
        ]

    # --- Required: message routing ---

    def supported_messages(self) -> dict[str, type]:
        return {
            "tool/list/req":  ToolListRequest,
            "tool/call/req":  ToolCallRequest,
        }

    def handle(self, msg):
        if isinstance(msg, ToolListRequest):
            return ToolListResponse(tools=self._list_tools())
        elif isinstance(msg, ToolCallRequest):
            return self._execute(msg)
        return None

    # --- Streaming support ---

    def set_event_callback(self, fn: Callable[[ToolEvent], None]):
        self._event_callback = fn

    def emit(self, kind: str, data: dict, req_id: str = ""):
        if self._event_callback:
            event = ToolEvent(kind=kind, data=data, req_id=req_id)
            self._event_callback(event)
```

The event callback is wired by `ToolPlugin.handle()` — when a `ToolCallRequest` arrives, a closure wraps the `ToolEvent` with the request's `req_id` and passes it to `self.emit_event()`, which routes through the executor's standard async event path. See [Plugin System → Event Emission](/architecture/plugin-system#event-emission-plugin-client) for the full architecture.

```python
    # --- ToolPlugin ABC ---

    def _list_tools(self) -> list[ToolDefinition]:
        return self._tools

    def _execute_tool(self, tool_name: str, arguments: dict) -> dict:
        if tool_name == "http_get":
            return self._http_get(arguments)
        elif tool_name == "http_post":
            return self._http_post(arguments)
        raise ValueError(f"Unknown tool: {tool_name}")

    def _execute(self, msg: ToolCallRequest) -> ToolCallResponse:
        """Safe execution wrapper with streaming, error handling, and audit."""
        t0 = time.time()
        req_id = msg.id

        try:
            # Emit progress event
            self.emit("progress", {"pct": 0, "message": f"Calling {msg.tool_name}..."}, req_id)

            result_data = self._execute_tool(msg.tool_name, msg.arguments)
            duration_ms = int((time.time() - t0) * 1000)

            self.emit("progress", {"pct": 100, "message": "Complete"}, req_id)

            result = ToolResult(
                success=True,
                tool_name=msg.tool_name,
                data=result_data,
                summary=f"HTTP {result_data.get('status_code', '?')} response",
                duration_ms=duration_ms,
            )

            return ToolCallResponse(data=result)

        except Exception as exc:
            duration_ms = int((time.time() - t0) * 1000)
            result = ToolResult(
                success=False,
                tool_name=msg.tool_name,
                error=str(exc),
                error_code="TOOL_ERROR",
                duration_ms=duration_ms,
            )
            return ToolCallResponse(data=result)

    # --- Tool implementations ---

    def _http_get(self, args: dict) -> dict:
        url = args["url"]
        headers = args.get("headers", {})
        timeout = args.get("timeout", 30)

        self.emit("status", {"message": f"GET {url}"}, "")

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return {
                    "status_code": resp.status,
                    "body": body,
                    "headers": dict(resp.headers),
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return {
                "status_code": e.code,
                "body": body,
                "error": str(e.reason),
            }

    def _http_post(self, args: dict) -> dict:
        url = args["url"]
        body = json.dumps(args["body"]).encode("utf-8")
        headers = args.get("headers", {})
        headers.setdefault("Content-Type", "application/json")
        timeout = args.get("timeout", 30)

        self.emit("status", {"message": f"POST {url}"}, "")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read().decode("utf-8", errors="replace")
                return {
                    "status_code": resp.status,
                    "body": resp_body,
                    "headers": dict(resp.headers),
                }
        except urllib.error.HTTPError as e:
            resp_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return {
                "status_code": e.code,
                "body": resp_body,
                "error": str(e.reason),
            }

    # --- State persistence ---

    def save_state(self, store, key, session_id):
        # Stateless plugin — nothing to persist
        pass

    def restore_state(self, store, key, session_id):
        pass

    def clear_state(self, store, key, session_id):
        pass
```

### Register in Config

```yaml
plugins:
  - name: http_tools
    type: tools
    cls: my_package.http_tools.HTTPToolsPlugin
    metadata:
      enabled: true
      priority: 5
```

## Client Side: Using Tools from an Agent

### Basic Usage

```python
import logging
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.tools.client import ToolAPI

logger = logging.getLogger("tool-agent")

config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
transport = server.start()

client = A2EClient(transport, logger, agent_caps=["tools"])
client.connect()

tools = ToolAPI(client)

# ============================================================
# 1. List available tools
# ============================================================

tool_list = tools.list()
for t in tool_list:
    print(f"  {t.name} (v{t.version}): {t.description}")
    for p in t.input_parameters:
        req = "required" if p.required else "optional"
        print(f"    - {p.name} ({p.type}, {req}): {p.description}")

# Filter by tags
network_tools = tools.list(tags=["network"])
print(f"Network tools: {[t.name for t in network_tools]}")

# ============================================================
# 2. Simple tool call
# ============================================================

result = tools.call(
    tool_name="http_get",
    arguments={
        "url": "https://api.example.com/status",
        "timeout": 15,
    },
)

if result.success:
    print(f"Status: {result.data['status_code']}")
    print(f"Body: {result.data['body'][:200]}")
    print(f"Took {result.duration_ms}ms")
else:
    print(f"Failed: {result.error_code} - {result.error}")

# ============================================================
# 3. Streaming tool call with event callbacks
# ============================================================

def on_event(event):
    """Handle streaming ToolEvents during execution."""
    if event.kind == "progress":
        print(f"  [{event.data['pct']}%] {event.data['message']}")
    elif event.kind == "status":
        print(f"  Status: {event.data['message']}")
    elif event.kind == "artifact":
        print(f"  Artifact chunk: {event.data.get('chunk', '')[:100]}")
    elif event.kind == "log":
        print(f"  [{event.data['level']}] {event.data['message']}")

result = tools.call(
    tool_name="http_post",
    arguments={
        "url": "https://api.example.com/data",
        "body": {"key": "value", "count": 42},
        "headers": {"Authorization": "Bearer my-token"},
    },
    streaming=True,
    on_event=on_event,
    timeout=60.0,
)

if result.success:
    print(f"POST response: {result.data['status_code']}")
    print(f"Summary: {result.summary}")
else:
    print(f"Error: {result.error}")

# ============================================================
# 4. POST with JSON body
# ============================================================

result = tools.call(
    tool_name="http_post",
    arguments={
        "url": "https://api.example.com/submit",
        "body": {
            "name": "task-1",
            "payload": {"items": [1, 2, 3]},
            "priority": "high",
        },
    },
)
print(f"Submit result: {result.data}")

# ============================================================
# 5. Error handling patterns
# ============================================================

# Tool not found
result = tools.call(tool_name="nonexistent_tool", arguments={})
# result.success == False, result.error_code == "UNKNOWN_TOOL"

# Tool denied by policy
result = tools.call(tool_name="http_post", arguments={"url": "..."})
# result.success == False, result.error_code == "TOOL_DENIED"

# Execution failure (e.g., timeout)
result = tools.call(tool_name="http_get", arguments={"url": "http://slow.example.com"}, timeout=1)
# result.success == False, result.error_code == "TOOL_ERROR"

# ============================================================
# 6. Correlation IDs for tracing
# ============================================================

result = tools.call(
    tool_name="http_get",
    arguments={"url": "https://api.example.com/data"},
    correlation_id="turn-5-tool-call-1",  # Ties to agent turn for audit
)

# ============================================================
# 7. Using ToolResult fields
# ============================================================

result = tools.call(tool_name="http_get", arguments={"url": "https://example.com/large"})
if result.success:
    # Check if output was truncated
    if result.truncated:
        print("Output was truncated — request larger page size or stream")

    # Access structured data
    print(f"Status: {result.data.get('status_code')}")

    # Human-readable summary (plugin-provided)
    print(f"Summary: {result.summary}")

    # Process exit code (for shell-based tools)
    if result.exit_code is not None:
        print(f"Exit code: {result.exit_code}")

    # Duration
    print(f"Duration: {result.duration_ms}ms")

    # Collected streaming events (if any)
    for event in result.events:
        print(f"  Event: {event.kind} -> {event.data}")

client.disconnect()
```

## Tool Result Shape Reference

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | `bool` | Yes | True if tool executed without error |
| `tool_name` | `str` | Yes | Name of the tool that ran |
| `data` | `Any` | No | Result payload (shape depends on tool) |
| `summary` | `str` | No | Human-readable one-liner |
| `truncated` | `bool` | Yes | Output was cut short |
| `exit_code` | `int` | No | Process exit code (shell tools) |
| `error` | `str` | No | Error message on failure |
| `error_code` | `str` | No | Machine-readable: `UNKNOWN_TOOL`, `TOOL_DENIED`, `TOOL_ERROR` |
| `duration_ms` | `int` | Yes | Wall-clock execution time |
| `events` | `list` | Yes | Collected streaming events |

## Event Kinds

| Kind | Data Shape | When Emitted |
|------|-----------|--------------|
| `progress` | `{pct: int, message: str}` | Progress updates during long operations |
| `status` | `{message: str}` | One-liner status change |
| `artifact` | `{name: str, mime: str, chunk: str, final: bool}` | Incremental data chunks |
| `log` | `{level: str, message: str}` | Debug/info/warning log lines |

## Tips

- **Define output_parameters**: They document the result shape for the agent and enable client-side validation.
- **Set idempotent=True** for safe-to-retry tools (GET requests, read-only operations).
- **Tag your tools**: Tags enable filtered listing — use `tags=["network", "read"]` etc.
- **Emit streaming events** for long-running tools; the agent can show progress to the user.
- **Use correlation_id**: Ties tool calls to agent turns for audit and tracing.
- **Handle errors gracefully**: Return `ToolResult(success=False, error=...)` rather than raising exceptions — the plugin wrapper converts uncaught exceptions to `A2EError`.
- **Keep tools stateless**: Tools should not carry state between calls. If you need state, use the memory capability instead.
