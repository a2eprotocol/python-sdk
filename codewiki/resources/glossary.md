# Glossary

A comprehensive reference for terms, acronyms, and concepts used throughout the A2E protocol and SDK documentation.

---

## A

### A2E
**Agent-to-Environment** — the protocol and Python SDK that standardizes how LLM agents interact with stateful environments. Think of it as "POSIX for AI agents."

### A2EClient
The client-side runtime class (`a2e.core.client.client.A2EClient`) that manages transport connections, performs handshakes, and provides the `rpc()` method for sending requests and receiving responses with event streaming.

### A2EError
The standard error message format returned when an operation fails. Contains `code`, `message`, `detail`, `retryable`, and `capability_name` fields. See [Error Codes](/protocol-spec/error-codes).

### A2EHostConfig
The top-level Pydantic configuration model (`a2e.schema.A2EHostConfig`) that defines server, transport, audit, and plugin settings. Loaded from YAML via `from_yaml()`.

### A2EMessage
The base Pydantic model for all protocol messages. Contains `type`, `id`, `a2e` (version), and `ts` (timestamp) fields. Every message on the wire is an instance of an `A2EMessage` subclass.

### A2EPlugin
The abstract base class (`a2e.core.plugins.interface.A2EPlugin`) that all capability plugins extend. Defines `setup()`, `handle()`, `audit_handle()`, and `supported_messages()` hooks.

### A2EServer
The server-side runtime (`a2e.core.server.server.A2EServer`) that accepts connections (HTTP or Direct), creates sessions, and routes messages through the executor.

### A2EServerRuntimeExecutor
The dispatch core (`a2e.core.server.executor.A2EServerRuntimeExecutor`) that decodes NDJSON lines, dispatches to plugins via the type registry, and sends responses back through the transport.

### Accepted Caps
The list of `Capability` objects returned in a `HandshakeResponse`, indicating which of the agent's requested capabilities are available on the host. See [Capability Negotiation](/protocol-spec/capability-negotiation).

### Agent
An autonomous LLM-based entity that connects to an A2E host, negotiates capabilities, and interacts with the environment via tool calls, memory operations, and other capability APIs.

### Agent Caps
The list of capability names (e.g. `["tools", "memory", "env"]`) that an agent requests during handshake. The host matches these against its loaded plugins.

### Audit Entry
A structured log record (`AuditEntry`) created for every plugin handler invocation. Contains timing, byte sizes, success/error status, and correlation IDs. See [Audit System](/sdk-reference/audit).

### Auth Token
A shared secret string used during handshake to authenticate the agent. Currently the only authentication mechanism in A2E. Configured in `A2EHostConfig.server.auth_token`.

---

## B

### BaseTransport
The abstract base class (`a2e.core.transports.base.BaseTransport`) defining the transport interface: `start()`, `send()`, `deliver()`, and handler slots. See [Transport Layer](/architecture/transport-layer).

---

## C

### Capability
One of nine named functional namespaces that an agent can negotiate during handshake: `tools`, `memory`, `env`, `proc`, `learn`, `skills`, `toolkits`, `chains`, `mcp`. Each maps to a plugin type.

### Capability Registry
An internal registry on the host that maps `A2ECapability` enum values to loaded plugins. Used during handshake negotiation to determine `accepted_caps`.

### Chain
A directed acyclic graph (DAG) of processing nodes that the host executes in topological order. Supports `action`, `branch`, `map`, `gather`, and `reduce` node kinds. See [Chains capability](/capabilities/chains).

### Client API
High-level Python classes (e.g. `ToolAPI`, `MemoryAPI`) that wrap `A2EClient.rpc()` to provide convenient methods like `tools.call()`, `memory.recall()`. See [Client API Reference](/sdk-reference/client-api).

### Configuration
The YAML file or `A2EHostConfig` object that defines host settings, transport type, audit options, and plugin list. See [Configuration](/sdk-reference/configuration).

### Correlation ID
A unique identifier (`id` field) assigned to every request message. The corresponding response echoes this as `req_id`, enabling request-response matching in the RPC pattern.

---

## D

### DAG
**Directed Acyclic Graph** — the structure used by the `chains` capability. Nodes have directional edges with no cycles, enabling parallel and conditional execution.

### DirectTransport
An in-process transport (`a2e.core.transports.direct.DirectTransport`) using cross-wired queues. Used for local testing, RL step loops, and in-process communication without network overhead.

### Dispatch
The process by which the executor routes an incoming message to one or more plugin handlers based on the message's `type` field and the plugin type registry.

---

## E

### Episode
A scoped sequence of interactions in the `env` (RL environment) capability. Each episode has `reset()` and `step()` operations with isolated state.

### Event Streaming
The mechanism by which the client receives `A2EEvent` messages (progress, artifact, log, status) before the final RPC response via an `event_callback`. Enabled through SSE in HTTP mode.

### Exclusive Plugin
A plugin declared with `exclusive=True` that receives sole handling of its message types. Non-exclusive plugins broadcast to all registered handlers for the type.

---

## F

### FastAPI
The ASGI web framework used by `A2EServer` in HTTP mode. Provides POST `/send` and GET `/stream` (SSE) endpoints.

---

## G

### Gather Node
A chain node kind that collects outputs from multiple fan-out paths and produces a single merged result.

---

## H

### Handshake
The first message exchange in any A2E session. The agent sends `handshake/req` with its capabilities and auth token; the host responds with `handshake/resp` including accepted capabilities and session ID. See [Handshake](/protocol-spec/handshake).

### Host
The A2E server that loads plugins, manages sessions, and processes agent requests. Often used interchangeably with "server" in documentation.

---

## I

### In-Memory Transport
See [DirectTransport](#directtransport).

---

## L

### Learning
The `learn` capability for feedback loops, experience storage, and skill adaptation. Supports `POSITIVE`, `NEGATIVE`, `NEUTRAL`, and `CORRECTIVE` feedback types. See [Learning capability](/capabilities/learn).

---

## M

### Map Node
A chain node kind that fans out execution across a list of items, applying the same sub-node to each.

### MCP
**Model Context Protocol** — an open protocol for connecting AI systems to external tools and data sources. The `mcp` capability bridges MCP servers into the A2E ecosystem, proxying MCP tools as A2E tools. See [MCP Bridge capability](/capabilities/mcp).

### Memory
The `memory` capability providing a three-tier storage model: **working** (scratchpad), **episodic** (timestamped events), and **semantic** (searchable knowledge). See [Memory capability](/capabilities/memory).

### Message Type
A string identifier (e.g. `tool/call/req`, `memory/recall/resp`) that routes messages to the correct handler. Follows the pattern `namespace/verb/suffix`.

---

## N

### NDJSON
**Newline-Delimited JSON** — the wire format for A2E messages. Each line is a complete JSON object representing one message.

### Node
An execution unit within a chain pipeline. Each node has a `kind` (action, branch, map, gather, reduce) and processes inputs to produce outputs.

---

## P

### Plugin
A Python class extending `A2EPlugin` that implements capability-specific logic. Loaded dynamically by the host at startup. See [Plugin System](/architecture/plugin-system).

### Plugin Registry
The host's internal registry (`PluginRegistry`) that maps message types to plugin handler methods. Populated during startup by calling each plugin's `supported_messages()`.

### Priority
An integer value declared by each plugin (default: 0). When multiple plugins handle the same message type, they are sorted by priority. Higher values are dispatched first.

### Proc
The `proc` capability for managing long-running subprocesses: spawn, write stdin, read stdout/stderr, signal, and kill. See [Processes capability](/capabilities/proc).

### Protocol Version
The `a2e` field in every message, currently `"1.0"`. Checked during handshake to ensure client-server compatibility.

---

## R

### Reduce Node
A chain node kind that aggregates a collection of items into a single result using a specified reduction function.

### RPC
**Remote Procedure Call** — the request-response pattern used by `A2EClient.rpc()`. Sends a request message, waits for a response with matching `req_id`, and optionally receives streaming events.

---

## S

### Sandbox
An isolated execution environment, typically a Docker container, used by the `skills` capability to safely run arbitrary code.

### Schema Violation
An error code (`schema_violation`) returned when a message fails Pydantic validation. Indicates the message structure does not match the expected model.

### SDK
**Software Development Kit** — the `a2e` Python package providing `A2EClient`, `A2EServer`, plugin base classes, and capability APIs.

### Semantic Memory
The long-term, searchable knowledge tier in the memory capability. Stores key-value pairs with optional tags, TTL, and full-text search support.

### Session
An isolated execution context created per connection. Each session has its own `A2EServerRuntimeExecutor`, `DirectTransport`, and state. See [Session Management](/architecture/session-management).

### Session Manager
The component (`SessionManager`) that creates and tracks sessions in HTTP mode. Maps session IDs to their executors and SSE streams.

### Skill
A named, versioned capability unit in the `skills` namespace. Skills have `input_schema`, `output_schema`, and `instructions`. Can be discovered, called, and adapted.

### Snapshot / Restore
The session persistence mechanism. A session's state can be saved (snapshot) to disk or SQLite and later restored to resume from that point.

### SSE
**Server-Sent Events** — the HTTP streaming mechanism used for delivering real-time events and responses from the host to the client. Accessed via GET `/stream`.

### Subagent
A spawned child agent within the multi-agent capability. Supports `shared`, `restricted`, `isolated`, and `snapshot` memory scopes with depth and step limits.

---

## T

### Three-Layer Design
A2E's architecture organized into: (1) Protocol Layer (schemas/messages), (2) Runtime Layer (server/client/transport), and (3) Capability Layer (9 plugin namespaces). See [Architecture Overview](/architecture/overview).

### Tier (Memory)
One of three storage levels in the memory capability: **working** (short-term scratchpad), **episodic** (timestamped events), **semantic** (searchable knowledge).

### Toolkit
A named bundle of related tools in the `toolkits` capability. Has a JSON Schema for configuration and lifecycle states (installed, configured, running). See [Toolkits capability](/capabilities/toolkits).

### Tool
A named, callable function in the `tools` capability. Has a JSON Schema for input parameters and returns structured results. See [Tools capability](/capabilities/tools).

### Transport
The communication layer abstraction. Two production implementations: `HTTPTransport` (POST + SSE) and `DirectTransport` (in-process queues). See [Transport Layer](/architecture/transport-layer).

### TTL
**Time-To-Live** — an optional expiration setting on memory entries. After the TTL elapses, the entry is considered expired and may be garbage-collected.

### Type Map
A dictionary mapping message type strings (e.g. `"tool/call/req"`) to Pydantic model classes. Each capability namespace defines its own `TYPE_MAP`, which the host merges into the global type registry.

### Type Registry
The host's combined mapping of all message types to their Pydantic model classes. Used for polymorphic NDJSON decoding — look up the model by `type` field, then validate and instantiate.

---

## V

### Version Mismatch
An error code (`version_mismatch`) returned during handshake when the client's protocol version does not match the server's supported version.

---

## W

### Working Memory
The short-term scratchpad tier in the memory capability. Stores ephemeral key-value pairs for the current session with optional size limits.

