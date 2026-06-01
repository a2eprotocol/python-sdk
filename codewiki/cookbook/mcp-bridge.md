# MCP Bridge Plugin & Client Example

## Overview

The MCP Bridge connects A2E to the external MCP ecosystem. This cookbook covers two scenarios:

1. **Plugin side**: Writing a custom MCP gateway adapter (e.g., for a new transport type)
2. **Client side**: Full agent-side usage — registering servers, calling tools, reading resources, using prompts, and handling sampling requests

## Plugin Side: Custom MCP Transport Adapter

The built-in `MCPPlugin` delegates to `MCPGateway`, which manages a pool of `MCPConnection` subclasses. To support a new transport (e.g., WebSocket), implement the `MCPConnection` ABC:

```python
import json
import asyncio
import websockets
from a2e.caps.mcp.mcp_gateway import MCPConnection

class WSMCPConnection(MCPConnection):
    """WebSocket transport adapter for MCP servers."""

    def __init__(self, config, on_push=None, on_sampling=None):
        super().__init__(config, on_push=on_push, on_sampling=on_sampling)
        self._ws = None
        self._request_id = 0
        self._pending = {}  # request_id -> Future

    # --- Connection lifecycle ---

    async def connect(self):
        """Open WebSocket and perform MCP handshake."""
        headers = self.config.headers or {}
        self._ws = await websockets.connect(
            self.config.url,
            extra_headers=headers,
        )
        # Start reader task
        asyncio.create_task(self._reader())

        # MCP handshake: initialize + initialized notification
        await self._do_initialize()

    async def disconnect(self):
        if self._ws:
            await self._ws.close()
            self._ws = None

    # --- JSON-RPC 2.0 transport ---

    async def _send_request(self, method, params, timeout=30):
        """Send a JSON-RPC request and await the response."""
        self._request_id += 1
        rid = self._request_id
        msg = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params or {},
        }
        future = asyncio.get_event_loop().create_future()
        self._pending[rid] = future
        await self._ws.send(json.dumps(msg))

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise TimeoutError(f"MCP request {method} timed out after {timeout}s")

    async def _send_notification(self, method, params=None):
        """Send a JSON-RPC notification (no response expected)."""
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        await self._ws.send(json.dumps(msg))

    async def _reader(self):
        """Background reader: resolve pending requests, forward notifications."""
        async for raw in self._ws:
            msg = json.loads(raw)

            # Response to a pending request
            if "id" in msg and msg["id"] in self._pending:
                future = self._pending.pop(msg["id"])
                if "error" in msg:
                    future.set_exception(
                        RuntimeError(f"MCP error: {msg['error']}")
                    )
                else:
                    future.set_result(msg.get("result"))
                continue

            # Server-initiated notification
            if "method" in msg and self._on_push:
                self._on_push(
                    method=msg["method"],
                    params=msg.get("params", {}),
                )

    # --- MCP operations (override base class) ---

    async def _do_initialize(self):
        """MCP handshake: initialize -> initialized -> cache tools/resources/prompts."""
        result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "a2e-mcp-bridge", "version": "1.0"},
        })
        self._server_info = result.get("serverInfo", {})
        self._mcp_version = result.get("protocolVersion", "")

        # Notify initialized
        await self._send_notification("notifications/initialized")

        # Cache tools, resources, prompts
        tools = await self._send_request("tools/list", {})
        self.tools = tools.get("tools", [])

        try:
            resources = await self._send_request("resources/list", {})
            self.resources = resources.get("resources", [])
        except Exception:
            self.resources = []

        try:
            prompts = await self._send_request("prompts/list", {})
            self.prompts = prompts.get("prompts", [])
        except Exception:
            self.prompts = []

    async def call_tool(self, tool_name, arguments):
        """Call an MCP tool on the server."""
        return await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

    async def read_resource(self, uri):
        """Read an MCP resource by URI."""
        return await self._send_request("resources/read", {"uri": uri})

    async def get_prompt(self, name, arguments=None):
        """Render an MCP prompt template."""
        return await self._send_request("prompts/get", {
            "name": name,
            "arguments": arguments or {},
        })
```

### Registering the WS transport in MCPGateway

Extend the gateway factory to support `ws` transport:

```python
# In your custom MCPGateway subclass or monkey-patch:
from a2e.caps.mcp.mcp_gateway import MCPGateway

_original_create = MCPGateway._create_connection

async def _create_connection(self, config, **kwargs):
    if config.transport == "ws":
        conn = WSMCPConnection(config, **kwargs)
        await conn.connect()
        return conn
    return await _original_create(self, config, **kwargs)

MCPGateway._create_connection = _create_connection
```

### Config with WS transport

```yaml
# config.yaml
plugins:
  - name: mcp
    type: mcp
    cls: a2e.caps.mcp.plugin.MCPPlugin
    metadata:
      enabled: true
      priority: 10
```

Then the agent registers the WS server at runtime (see client examples below).

## Client Side: Full MCP Agent Usage

### 1. Server Registration

```python
import logging
from a2e.schema import A2EHostConfig, MCPServerConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.mcp.client import MCPAPI
from a2e.caps.tools.client import ToolAPI

logger = logging.getLogger("mcp-agent")

config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
transport = server.start()

client = A2EClient(transport, logger, agent_caps=["mcp", "tools"])
client.connect()

mcp = MCPAPI(client)
tools = ToolAPI(client)

# --- Register a stdio MCP server ---
info = mcp.register_server("local_fs", MCPServerConfig(
    server_id="local_fs",
    name="Local Filesystem",
    transport="stdio",
    cmd=["python", "-m", "mcp_server_filesystem"],
    cwd="/home/user",
    tool_allow_list=["read_file", "write_file", "list_directory"],
))
print(f"Registered: {info.name}, tools: {[t.name for t in info.tools]}")

# --- Register an SSE MCP server ---
info2 = mcp.register_server("remote_api", MCPServerConfig(
    server_id="remote_api",
    name="Remote API",
    transport="sse",
    url="http://api.example.com:8081/sse",
    headers={"Authorization": "Bearer token123"},
))
print(f"Registered: {info2.name}, status: {info2.status}")

# --- Register a WebSocket MCP server (using custom transport) ---
info3 = mcp.register_server("ws_server", MCPServerConfig(
    server_id="ws_server",
    name="WebSocket Tools",
    transport="ws",
    url="ws://localhost:9000/mcp",
))
```

### 2. Tool Discovery and Execution

```python
# MCP tools are auto-synced into the ToolRegistry with namespaced names:
#   server_id__tool_name
# They appear in regular tool/list/resp and are callable via ToolAPI.

# List all tools (includes MCP-synced tools)
all_tools = tools.list()
mcp_tools = [t for t in all_tools if t.toolkit == "mcp" or "__" in t.name]
for t in mcp_tools:
    print(f"  {t.name}: {t.description}")

# Call an MCP tool via ToolAPI (transparent, like any native tool)
result = tools.call(
    tool_name="local_fs__read_file",
    arguments={"path": "/home/user/data.txt"},
)
if result.success:
    print(f"File contents: {result.data}")
else:
    print(f"Error: {result.error}")

# Call with streaming events
def on_progress(event):
    print(f"  Progress: {event.data}")

result = tools.call(
    tool_name="remote_api__fetch_url",
    arguments={"url": "https://api.example.com/data"},
    streaming=True,
    on_event=on_progress,
    timeout=60.0,
)
```

### 3. Explicit MCP Routing via MCPAPI

```python
# MCPAPI provides explicit server-scoped routing:

# List all registered servers
servers = mcp.list_servers()
for s in servers:
    print(f"Server {s.server_id}: {s.name} [{s.status}] "
          f"tools={s.tools_count} resources={s.resources_count}")

# List tools from a specific server
fs_tools = mcp.list_tools("local_fs")

# Find which servers provide a tool
providers = mcp.find_tool("read_file")
print(f"Tool 'read_file' available on: {providers}")

# Call with explicit routing strategy
# strategy="first" -> use first server that has the tool
# strategy="all" -> try all servers, return first success
result = mcp.call_tool(
    tool_name="read_file",
    arguments={"path": "/home/user/data.txt"},
    strategy="first",
    tool_api=tools,
)
```

### 4. Resource Access

```python
# List resources from all servers
resources = mcp.list_resources()
for r in resources:
    print(f"[{r.server_id}] {r.uri} ({r.mime_type}): {r.name}")

# List resources from one server
fs_resources = mcp.list_resources(server_id="local_fs")

# Read a specific resource
content = mcp.read_resource("local_fs:///home/user/config.json")
print(f"Resource content: {content}")

# Subscribe to resource change notifications
mcp.subscribe_resource("local_fs:///home/user/config.json")
# The client receives mcp/server/push messages when the resource changes
```

### 5. Prompt Templates

```python
# List all prompt templates
prompts = mcp.list_prompts()
for p in prompts:
    print(f"[{p.server_id}] {p.name}: {p.description}")
    for arg in p.arguments:
        print(f"  Arg: {arg['name']} (required={arg.get('required', False)})")

# Render a prompt with arguments
prompt = mcp.get_prompt(
    name="summarize_file",
    arguments={"path": "/data/report.txt"},
    server_id="local_fs",
)
print(f"Prompt: {prompt.description}")
for msg in prompt.messages:
    print(f"  [{msg.role}]: {msg.content}")
```

### 6. Dynamic Registration & Cleanup

```python
# Register a server on-the-fly
mcp.register_server("temp_scraper", MCPServerConfig(
    server_id="temp_scraper",
    name="Web Scraper",
    transport="stdio",
    cmd=["python", "-m", "scraper_mcp_server"],
    env={"HEADLESS": "1"},
))

# Use it...
result = tools.call("temp_scraper__scrape", {"url": "https://example.com"})

# Unregister when done (tools auto-removed from registry)
mcp.unregister_server("temp_scraper")
```

### 7. Handling Sampling Requests (MCP -> Agent LLM)

When an MCP server requests LLM inference, the host forwards it as `mcp/sample/req`:

```python
# Option A: Automatic handling (if agent has LLM capability)
# The agent framework auto-responds using its LLM backend.

# Option B: Manual response
mcp.respond_sampling(
    request_id="sample-123",
    content="Generated text based on the request",
    model="my-model-name",
)
```

## Tool Syncing Under the Hood

When a server is registered, `MCPGateway` syncs tools into the host `ToolRegistry`:

```
MCP Server "local_fs" provides: read_file, write_file, list_directory
                    ↓ synced as
ToolRegistry: local_fs__read_file, local_fs__write_file, local_fs__list_directory
```

The tool runner is closure-bound to the specific connection:

```python
def _sync_tools(self, conn):
    for tool in conn.tools:
        namespaced = f"{conn.server_id}__{tool.name}"
        self.tool_registry.register(namespaced, tool, runner=conn.call_tool)
```

This means calling `local_fs__read_file` via `ToolAPI` transparently routes through the MCP gateway to the correct server — no MCPAPI needed for basic tool calls.

## Key Patterns

| Pattern | When to Use |
|---------|-------------|
| `mcp.register_server(id, config)` | Connect to a new MCP server |
| `tools.call("server__tool", args)` | Transparent MCP tool call (no MCPAPI needed) |
| `mcp.call_tool("tool", args, strategy=)` | Explicit routing across servers |
| `mcp.list_resources()` / `mcp.read_resource(uri)` | Access MCP resource URIs |
| `mcp.get_prompt(name, args)` | Render server-side prompt templates |
| `mcp.unregister_server(id)` | Disconnect and clean up a server |
| Custom `MCPConnection` subclass | Add new transport types (WS, gRPC, etc.) |

## Tips

- **Allow lists**: Use `tool_allow_list` and `resource_allow_list` on `MCPServerConfig` to restrict what the agent can access.
- **Auto-reconnect**: Set `auto_reconnect=True` (default) for production servers; the gateway reconnects on disconnect.
- **Namespace collisions**: Tool names are namespaced as `server_id__tool_name` — pick unique server IDs.
- **Push notifications**: Subscribe to resources for real-time updates; handle `mcp/server/push` for `tools/list_changed`.
- **Timeout tuning**: Set `timeout` on `MCPServerConfig` per-server; slow servers get higher timeouts.
- **Transport choice**: Use `stdio` for local processes, `sse` for remote HTTP servers, `ws` for persistent bidirectional connections.
