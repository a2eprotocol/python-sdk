# Tools

```text
a2e/caps/tools/protocol.py — MessageType, ToolDefinition, ToolCall*, ToolResult
a2e/caps/tools/plugin.py   — ToolPlugin ABC
a2e/caps/tools/client.py   — ToolAPI
```

Tools are the atomic unit of agent action — the functions an agent can call to read files, execute commands, query APIs, or interact with the world. In the A2E model, every tool call is a typed `tool/call/req` message, making execution auditable, interruptible, and swappable across backends.

## Overview

The **tools** capability provides native environment tool execution — primitive operations like file I/O, shell commands, HTTP requests, and code evaluation. Tools are the most fundamental building block for agent interaction.

## Protocol Messages (5 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `tool/list/req` | `ToolListRequest` | Agent → Host |
| `tool/list/resp` | `ToolListResponse` | Host → Agent |
| `tool/call/req` | `ToolCallRequest` | Agent → Host |
| `tool/call/resp` | `ToolCallResponse` | Host → Agent |
| `tool/event` | `ToolEvent` | Host → Agent (streaming) |

### ToolDefinition

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique tool name (e.g. `"read_file"`) |
| `description` | `str` | What the tool does |
| `input_parameters` | `list[ToolParameter]` | Input schema |
| `output_parameters` | `list[ToolParameter]` | Output schema |
| `streaming` | `bool` | Supports streaming events |
| `idempotent` | `bool` | Safe to retry |
| `tags` | `list[str]` | Classification tags |
| `version` | `str` | Tool version |
| `toolkit` | `str` | Parent toolkit name |

### ToolParameter

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Parameter name |
| `type` | `str` | JSON Schema type (`string`, `number`, `object`, etc.) |
| `description` | `str` | Parameter description |
| `required` | `bool` | Whether this parameter is required |
| `enum` | `list` | Allowed values |
| `properties` | `list[ToolParameter]` | Nested object properties |

### ToolCallRequest

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Session identifier |
| `tool_name` | `str` | Tool to invoke |
| `arguments` | `dict` | Input arguments |
| `correlation_id` | `str` | Optional correlation |
| `streaming` | `bool` | Request streaming events |
| `timeout` | `float` | Execution timeout |

### ToolResult

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Whether execution succeeded |
| `data` | `dict` | Result data |
| `summary` | `str` | Human-readable summary |
| `truncated` | `bool` | Output was truncated |
| `exit_code` | `int` | Process exit code (if applicable) |
| `error` | `str` | Error message |
| `error_code` | `ToolErrorCode` | Machine-readable error |
| `duration_ms` | `int` | Execution time |
| `events` | `list[ToolEvent]` | Collected streaming events |

### ToolEvent (extends A2EEvent)

Streaming mid-call events with `kind`: `progress`, `status`, `artifact`, `log`.

### ToolErrorCode

| Code | Description |
|------|-------------|
| `UNKNOWN_TOOL` | Tool name not found |
| `TOOL_DENIED` | Tool not allowed by policy |
| `TOOL_ERROR` | Tool execution failed |

## ToolPlugin ABC

```python
class ToolPlugin(A2EPlugin):
    name = "base_tool"

    @abstractmethod
    def _list_tools(self) -> list[ToolDefinition]: ...

    @abstractmethod
    def _execute_tool(self, tool_name: str, arguments: dict) -> dict: ...

    def set_event_callback(self, cb): ...
    def emit(self, kind, data): ...  # Build and send ToolEvent
```

**Handler**: `handle(msg)` dispatches:
- `ToolListRequest` → calls `_list_tools()`, returns `ToolListResponse`
- `ToolCallRequest` → calls `_execute_tool()`, returns `ToolCallResponse` or `A2EError`

## ToolAPI (Client)

```python
from a2e.caps.tools.client import ToolAPI

tools = ToolAPI(client)

# List available tools
tool_list = tools.list(kind=None, tags=None)
# Returns List[ToolDefinition]

# Call a tool
result = tools.call(
    tool_name="read_file",
    arguments={"path": "/etc/hostname"},
    streaming=False,       # Enable streaming events
    on_event=None,         # Callback for ToolEvents
    timeout=30.0,
    correlation_id=None
)
# Returns ToolResult

if result.success:
    print(result.data)
else:
    print(f"Error: {result.error_code} - {result.error}")
```

**Caching**: `tools.list()` caches results in `client._tools_cache`.
