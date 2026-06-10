# Quick Start

## What is A2E?

A2E (Agent-to-Environment) is a protocol and Python runtime for building **stateful, interactive environments** that LLM agents can interact with. It standardizes how agents use tools, access memory, run processes, observe environments, and learn from feedback — enabling a shift from static prompting to dynamic interaction.

Think of it as **"POSIX for AI agents"** — a unified interface between intelligent agents and the environments they operate in.

## Install

```bash
# pip
pip install a2e

# or uv
uv pip install a2e
```

If installing from source, see [Installation Details](/getting-started/installation).

## Minimal Server

Create a `config.yaml`:

```yaml
host_id: "my-a2e-host"
server:
  host: "0.0.0.0"
  port: 8765
auth_token: "dev-secret"
transport:
  type: http
audit:
  enabled: true
  path: "/tmp/a2e-audit.jsonl"
plugins:
  - name: mytools
    type: tools
    cls: cookbook.servers.tools.registry_tool_plugin.RegistryToolPlugin
    metadata:
      enabled: true
      modules:
        - cookbook.servers.tools.read_file_tool
        - cookbook.servers.tools.glob_tool
  - name: mymemory
    type: memory
    cls: cookbook.servers.memory.inmemory.InMemoryPlugin
    metadata:
      enabled: true
      working_limit: 50
      episodic_limit: 50
      semantic_limit: 50
```

Start the server:

```python
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer

config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
app = server.start()  # Returns FastAPI app for HTTP mode

import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8765)
```

## Minimal Client

```python
from a2e.core.client.client import A2EClient
from a2e.core.transports import HTTPTransport, HTTPTransportConfig, build_transport
from a2e.caps.tools.client import ToolAPI
from a2e.caps.memory.client import MemoryAPI

# Build transport and connect
transport = build_transport(config.transport, logger=None)
client = A2EClient(
    transport=transport,
    agent_id="my-agent",
    auth_token="dev-secret",
    agent_caps=["tools", "memory"]
)

with client:
    # Use capability APIs
    tools = ToolAPI(client)
    memory = MemoryAPI(client)

    # List and call tools
    tool_list = tools.list()
    result = tools.call("read_file", {"path": "/etc/hostname"})

    # Store and retrieve memory
    memory.remember("user_name", "Alice", tier="working")
    name = memory.recall("user_name")  # Returns "Alice"
```

## What Happens Behind the Scenes

1. **Transport starts** — HTTP client connects to the server
2. **Handshake** — Client sends `handshake/req` with `agent_caps`, server responds with `accepted_caps`
3. **RPC calls** — Each `tools.call()` sends a `tool/call/req`, gets back `tool/call/resp` (with streaming events via `tool/event`)
4. **Disconnect** — Context manager sends `shutdown` and stops the transport

## Next Steps

- [Installation Details](/getting-started/installation)
- [Architecture Overview](/architecture/overview)
- [Client API Reference](/sdk-reference/client-api)
- [Protocol Specification](/protocol-spec/message-format)
