# Agent-to-Environment (A2E) Protocol

<p align="center">
  <img src="/assets/a2e-banner.png" alt="A2E Banner" width="800"/>
</p>

<div align="center">

**Python implementation of the Agent-to-Environment (A2E) Protocol**

[![PyPI version](https://img.shields.io/pypi/v/a2e.svg)](https://pypi.org/project/a2e/)
[![License](https://img.shields.io/github/license/a2eprotocol/python-sdk.svg)](./LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/a2e.svg)](https://pypi.org/project/a2e/)
[![Documentation](https://img.shields.io/badge/docs-online-blue.svg)](https://a2eprotocol.github.io/docs)
[![Protocol Spec](https://img.shields.io/badge/spec-A2E-green.svg)](https://a2eprotocol.github.io/docs/spec.md)

</div>

A2E (Agent-to-Environment) is a protocol and Python SDK for building **stateful, interactive environments** that LLM agents can interact with. It standardizes how agents use tools, access memory, run processes, observe environments, and learn from feedback — enabling a shift from **static prompting to dynamic interaction**.

> Think: **"POSIX for AI agents"** — a unified interface between intelligent agents and the environments they operate in.

---

## Why A2E?

Modern AI systems are moving beyond static inference toward:

- **Tool use** — agents that call functions with structured I/O
- **Multi-step reasoning** — agents that plan and chain operations
- **Long-running processes** — agents that spawn, monitor, and control subprocesses
- **Memory and learning** — agents that remember, adapt, and improve
- **Reinforcement learning** — agents that interact with environments and receive feedback

A2E provides a unified protocol for all of the above.

## Core Idea

A2E defines three things:

1. **A message protocol** — NDJSON-based, typed, versioned, with request/response/event patterns
2. **A pluggable runtime host** — a thin execution kernel that loads, routes, and manages plugins
3. **10 standard capability namespaces** — tools, memory, env, proc, learn, skills, toolkits, chains, mcp, subagents

Agents interact with environments via structured messages:

```
tool/call/req      → Call a named function
memory/store/req   → Store a value in memory
memory/recall/req  → Retrieve a value from memory
proc/spawn/req     → Spawn a long-running subprocess
env/step/req       → Take an action in an RL environment
learn/feedback/req → Provide feedback for adaptation
chain/execute/req  → Run a DAG pipeline
mcp/call_tool/req  → Proxy a call to an MCP server
toolkit/configure  → Configure a bundle of tools
subagent/spawn     → Spawn a child agent
```

---

## Architecture

A2E is organized into three clean layers:

```
┌─────────────────────────────────────────────────────────┐
│                    Protocol Layer                        │
│          Pydantic models, NDJSON wire format             │
│          A2EMessage, Handshake, TYPE_MAP                │
├─────────────────────────────────────────────────────────┤
│                    Runtime Layer                         │
│    A2EServer · A2EClient · Transport · Session          │
│    Executor · PluginRegistry · AuditLog                 │
├─────────────────────────────────────────────────────────┤
│                  Capability Layer                        │
│  ┌──────┬──────┬──────┬──────┬──────┬──────┬──────┐    │
│  │Tools │Memory│ Env  │ Proc │Learn │Skills│ MCP  │    │
│  │Plugin│Plugin│Plugin│Plugin│Plugin│Plugin│Plugin│    │
│  ├──────┼──────┼──────┼──────┴──────┴──────┴──────┤    │
│  │Toolkits │ Chains │ Subagents │                   │    │
│  │ Plugin  │Plugin  │  Plugin   │                   │    │
│  └─────────┴────────┴───────────┘                   │    │
└─────────────────────────────────────────────────────────┘
```

**Agent connects to Host** → Handshake negotiates capabilities → Agent uses capability APIs → Host dispatches to plugins → Plugins handle and respond.

---

## 10 Capability Namespaces

| Capability | Purpose | Plugin |
|-----------|---------|--------|
| `tools` | Call named functions with structured input/output | `ToolPlugin` |
| `memory` | Three-tier storage: working, episodic, semantic | `MemoryPlugin` |
| `env` | RL environment: reset, step, observe, reward | `EnvPlugin` |
| `proc` | Manage long-running subprocesses | `ProcPlugin` |
| `learn` | Feedback, experience storage, and adaptation | `LearnPlugin` |
| `skills` | Named, versioned, sandboxed execution units | `SkillPlugin` |
| `toolkits` | Bundles of tools with shared configuration | `ToolkitPlugin` |
| `chains` | DAG pipelines for multi-step processing | `ChainPlugin` |
| `mcp` | Bridge to Model Context Protocol servers | `MCPPlugin` |
| `subagents` | Multi-agent orchestration: spawn, delegate, merge | `SubagentPlugin` |

---

## Getting Started

### Install

```bash
pip install a2e
```

### Minimal Server

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
app = server.start()

import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8765)
```

### Minimal Client

```python
from a2e.core.client.client import A2EClient
from a2e.core.transports import build_transport
from a2e.caps.tools.client import ToolAPI
from a2e.caps.memory.client import MemoryAPI

transport = build_transport(config.transport, logger=None)
client = A2EClient(
    transport=transport,
    agent_id="my-agent",
    auth_token="dev-secret",
    agent_caps=["tools", "memory"]
)

with client:
    tools = ToolAPI(client)
    memory = MemoryAPI(client)

    # List and call tools
    tool_list = tools.list()
    result = tools.call("read_file", {"path": "/etc/hostname"})

    # Store and retrieve memory
    memory.remember("user_name", "Alice", tier="working")
    name = memory.recall("user_name")  # Returns "Alice"
```

---

## Plugin-Based Runtime

The host is a **thin execution kernel** — it loads, routes, and manages lifecycle. All capability-specific logic lives in dynamically loaded plugins.

```python
# Writing a custom plugin
from a2e.core.plugins.interface import A2EPlugin

class MyPlugin(A2EPlugin):
    def supported_messages(self):
        return {"my/capability/req": MyRequest}

    def handle(self, msg, ctx):
        # Process the message and return a response
        return MyResponse(result="done")
```

Register it in `config.yaml`:

```yaml
plugins:
  - name: myplugin
    type: tools
    cls: mypackage.MyPlugin
    metadata:
      enabled: true
```

---

## State & Persistence

A2E environments are stateful by design:

- **Snapshot / restore** — save and resume session state
- **Pluggable storage** — file-based or SQLite persistence
- **Structured audit logging** — every handler records timing, sizes, and success/error
- **Session isolation** — each connection gets its own executor and state

```yaml
audit:
  enabled: true
  path: "/var/log/a2e/audit.jsonl"
  rotate:
    max_bytes: 10485760   # 10 MB
    backup_count: 5
  session_id_source: "uuid"
```

---

## From Static to Interactive AI

| Traditional LLM | A2E |
|----------------|-----|
| Prompt → Response | Interaction loop |
| Stateless | Stateful sessions |
| No tools | 10 capability namespaces |
| No memory | 3-tier memory system |
| No learning | Feedback + adaptation |
| No processes | Subprocess management |
| Single step | Chain pipelines (DAG) |

---

## Documentation

Full documentation is available at [a2e-docs](https://github.com/a2eprotocol/docs) or in the [`./`](./) directory.

### Getting Started
- [Quick Start](./getting-started/quickstart.md) — Install, configure, and run in 5 minutes
- [Installation](./getting-started/installation.md) — Detailed setup instructions

### Architecture
- [Overview](./architecture/overview.md) — Three-layer design, system diagram, key patterns
- [Message Protocol](./architecture/message-protocol.md) — NDJSON wire format, message structure
- [Plugin System](./architecture/plugin-system.md) — Plugin lifecycle, registry, dispatch
- [Transport Layer](./architecture/transport-layer.md) — HTTP+SSE and DirectTransport
- [Session Management](./architecture/session-management.md) — Sessions, snapshots, restore

### SDK Reference
- [Client API](./sdk-reference/client-api.md) — `A2EClient`, `rpc()`, event streaming
- [Server API](./sdk-reference/server-api.md) — `A2EServer`, executor, plugin loading
- [Configuration](./sdk-reference/configuration.md) — `A2EHostConfig`, YAML reference
- [Audit System](./sdk-reference/audit.md) — `AuditEntry`, `AuditLog`, rotation
- [Persistence (Store)](./sdk-reference/store.md) — File and SQLite storage backends

### Capabilities
- [Tools](./capabilities/tools.md) — Named callable functions with JSON Schema I/O
- [Memory](./capabilities/memory.md) — Working, episodic, and semantic tiers
- [Environment](./capabilities/env.md) — RL environments: reset, step, observe
- [Processes](./capabilities/proc.md) — Subprocess spawning, I/O, signaling
- [Learning](./capabilities/learn.md) — Feedback, experience, adaptation
- [Skills](./capabilities/skills.md) — Named, versioned, sandboxed execution
- [Toolkits](./capabilities/toolkits.md) — Bundles of tools with shared config
- [Chains](./capabilities/chains.md) — DAG pipelines with branching and fan-out
- [MCP Bridge](./capabilities/mcp.md) — Model Context Protocol integration
- [Subagents](./capabilities/subagents.md) — Multi-agent orchestration: spawn, delegate, merge

### Protocol Specification
- [Message Format](./protocol-spec/message-format.md) — NDJSON, A2EMessage fields
- [Handshake](./protocol-spec/handshake.md) — Authentication and capability negotiation
- [Capability Negotiation](./protocol-spec/capability-negotiation.md) — How capabilities are matched
- [Message Types](./protocol-spec/message-types.md) — Full type registry reference
- [Error Codes](./protocol-spec/error-codes.md) — All error codes and retry strategies

### Cookbook
- [Writing a Plugin](./cookbook/writing-a-plugin.md) — Step-by-step plugin development
- [Environment Agent Loop](./cookbook/env-agent-loop.md) — RL step loop patterns
- [Chain Pipeline](./cookbook/chain-pipeline.md) — Building DAG pipelines
- [MCP Integration](./cookbook/mcp-integration.md) — Connecting MCP servers
- [MCP Bridge (Plugin & Client)](./cookbook/mcp-bridge.md) — Full MCP bridge implementation
- [Memory (Plugin & Client)](./cookbook/memory-plugin.md) — Custom memory plugin with SQLite
- [Custom Tools (Plugin & Client)](./cookbook/custom-tools.md) — HTTP tools plugin with streaming
- [Toolkit Builder (Plugin & Client)](./cookbook/toolkit-builder.md) — Database toolkit with schema config
- [Subagent Orchestrator (Plugin & Client)](./cookbook/subagent-orchestrator.md) — Multi-agent orchestration with depth control

### Resources
- [Glossary](./resources/glossary.md) — A-Z reference of A2E terms and concepts
- [FAQ](./resources/faq.md) — Frequently asked questions
- [Security & Trust](./resources/security-trust.md) — Security model, hardening, threat model
- [Support](./resources/support.md) — Troubleshooting, debugging, contributing
- [Changelog](./resources/changelog.md) — Release history and upgrade guide

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Protocol | NDJSON over Pydantic v2 |
| Server | FastAPI + Uvicorn |
| Transport | HTTP+SSE / In-process Direct |
| Schema | Pydantic BaseModel (validation + serialization) |
| Persistence | File / SQLite |
| Audit | RotatingFileHandler (JSONL) |

---

## Use Cases

- AI copilots with tool use
- Autonomous agents with memory and learning
- Reinforcement learning environments
- Data analyst agents with process management
- Multi-agent systems with isolation
- Code review and quality assurance agents
- MCP server aggregation

---

## Contributing

Contributions welcome! Especially:

- New plugins and capability implementations
- Protocol extensions and improvements
- Learning / RL integrations
- Tool ecosystems and toolkit packages
- Documentation improvements and cookbook recipes

See [Support](./resources/support.md) for contribution guidelines.

---

## License

MIT License
