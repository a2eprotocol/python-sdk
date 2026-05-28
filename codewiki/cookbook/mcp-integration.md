# MCP Integration Example

Connecting external MCP servers to your A2E agent.

## Basic MCP Server Registration

```python
import logging
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.mcp.client import MCPAPI
from a2e.caps.tools.client import ToolAPI

logger = logging.getLogger("mcp-agent")

config = A2EHostConfig.from_yaml("config.yaml")  # Must include mcp plugin
server = A2EServer(config)
transport = server.start()

client = A2EClient(transport, logger, agent_caps=["mcp", "tools"])
client.connect()

mcp = MCPAPI(client)
tools = ToolAPI(client)

# Register a stdio MCP server
info = mcp.register_server("local_fs", MCPServerConfig(
    server_id="local_fs",
    name="Local Filesystem",
    transport="stdio",
    cmd=["python", "-m", "mcp_server_filesystem"],
    cwd="/home/user",
    tool_allow_list=["read_file", "write_file", "list_directory"]
))
print(f"Registered: {info.name}, tools: {[t.name for t in info.tools]}")

# Register an SSE MCP server
info2 = mcp.register_server("remote_api", MCPServerConfig(
    server_id="remote_api",
    name="Remote API",
    transport="sse",
    url="http://api.example.com:8081/sse",
    headers={"Authorization": "Bearer token123"}
))

# MCP tools are automatically synced into the host tool registry
# Namespaced as: server_id__tool_name

# List all MCP tools
all_tools = tools.list()
mcp_tools = [t for t in all_tools if "__" in t.name]
print(f"MCP tools available: {[t.name for t in mcp_tools]}")

# Call an MCP tool via the normal ToolAPI
result = tools.call("local_fs__read_file", {"path": "/home/user/data.txt"})
print(result.data)

# Or use MCPAPI for explicit routing
result = mcp.call_tool("read_file", {"path": "/home/user/data.txt"}, strategy="first")
```

## Resource Access

```python
# List resources from all MCP servers
resources = mcp.list_resources()
for r in resources:
    print(f"[{r.server_id}] {r.uri} ({r.mime_type}): {r.name}")

# Read a specific resource
content = mcp.read_resource("local_fs:///home/user/config.json")
print(content)

# Subscribe to resource updates
mcp.subscribe_resource("local_fs:///home/user/config.json")
```

## Prompt Templates

```python
# List prompts from MCP servers
prompts = mcp.list_prompts()
for p in prompts:
    print(f"[{p.server_id}] {p.name}: {p.description}")

# Get a filled prompt
prompt = mcp.get_prompt("local_fs", "summarize_file", {"path": "/data/report.txt"})
print(prompt.messages)
```

## Dynamic Registration

MCP servers can be registered and unregistered at runtime:

```python
# Register on-the-fly
mcp.register_server("temp_server", MCPServerConfig(
    server_id="temp_server",
    name="Temporary",
    transport="stdio",
    cmd=["python", "-m", "my_temp_server"]
))

# Use it...

# Unregister when done
mcp.unregister_server("temp_server")
# All synced tools are automatically removed
```

## LLM Sampling (MCP → Agent)

When an MCP server needs LLM inference, it sends a sampling request through the gateway:

```python
# The agent handles this automatically if it has LLM capability
# The MCP gateway forwards the request as mcp/sampling/req

# Manual sampling response (if needed):
mcp.respond_sampling(request_id, content="Generated text", model="my-model")
```