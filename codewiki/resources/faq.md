# Frequently Asked Questions

Common questions about the A2E protocol, SDK, and runtime.

---

## General

### What is A2E?

A2E (Agent-to-Environment) is a protocol and Python SDK for building stateful, interactive environments that LLM agents can interact with. It standardizes how agents use tools, access memory, run processes, observe environments, and learn from feedback — enabling a shift from static prompting to dynamic interaction.

### How is A2E different from just using an LLM API?

LLM APIs give you text-in, text-out. A2E gives your agent a **persistent environment** with tools, memory, processes, and feedback loops. Instead of one-shot completions, the agent connects, negotiates capabilities, and maintains an interactive session where state persists across multiple calls.

### What does "POSIX for AI agents" mean?

POSIX standardized how programs interact with a Unix OS (files, processes, signals). A2E standardizes how AI agents interact with their environment (tools, memory, RL episodes, subprocess management). The host is the "OS," and the agent is the "program."

### Is A2E open source?

The A2E protocol specification and SDK are designed as an open standard. Check the project repository for licensing details.

---

## Getting Started

### What Python version do I need?

A2E requires Python 3.10 or later, due to its use of modern type hints, `match` statements, and Pydantic v2 features.

### How do I install A2E?

```bash
pip install a2e
```

For development with the server:

```bash
pip install "a2e[server]"
```

### What's the fastest way to try A2E?

Follow the [Quick Start](/getting-started/quickstart) guide. The minimal setup is a `config.yaml` with one plugin, then start the server with `uvicorn` and connect with `A2EClient`.

### Do I need Docker?

No. A2E runs as a pure Python process. Docker is only needed if you want sandboxed skill execution (the `skills` capability can run skills in containers for isolation).

---

## Architecture

### What are the three layers?

1. **Protocol Layer** — Pydantic models and message schemas (the wire format)
2. **Runtime Layer** — Server, client, transport, session management (the engine)
3. **Capability Layer** — 9 plugin namespaces implementing specific functionality (the features)

See [Architecture Overview](/architecture/overview).

### What are the 9 capability namespaces?

| Capability | Purpose |
|-----------|---------|
| `tools` | Call named functions with structured input/output |
| `memory` | Three-tier storage: working, episodic, semantic |
| `env` | RL environment: reset, step, observe, reward |
| `proc` | Manage long-running subprocesses |
| `learn` | Feedback, experience, and adaptation |
| `skills` | Named, versioned, sandboxed execution units |
| `toolkits` | Bundles of tools with shared configuration |
| `chains` | DAG pipelines for multi-step processing |
| `mcp` | Bridge to Model Context Protocol servers |

### Why is everything a plugin?

The host is intentionally a thin execution kernel. All capability-specific logic lives in dynamically loaded plugins. This means you can add new capabilities without touching the core runtime, and you can swap implementations without changing the protocol.

### What transport options are available?

- **HTTPTransport** — Production: POST `/send` + GET `/stream` (SSE) with session management and reconnection
- **DirectTransport** — In-process: cross-wired queues, zero network overhead. Used for testing and RL step loops

See [Transport Layer](/architecture/transport-layer).

---

## Protocol

### What wire format does A2E use?

NDJSON (Newline-Delimited JSON). Each line is a complete JSON object representing one message. This is simple, debuggable, and supports streaming.

### How does request-response matching work?

Every request has a unique `id` field. The response echoes this as `req_id`. The client's `rpc()` method correlates requests and responses using a queue keyed by `req_id`.

### Can I get streaming responses?

Yes. The client's `rpc()` method accepts an `event_callback` that receives `A2EEvent` messages (progress, artifact, log, status) before the final response arrives. This enables real-time UI updates for long-running operations.

### What happens during handshake?

1. Client sends `handshake/req` with `agent_id`, `agent_caps`, and `auth_token`
2. Host validates auth, matches capabilities against loaded plugins
3. Host responds with `handshake/resp` containing `accepted_caps`, `session_id`, and `max_parallel`
4. If `ok=false`, the session is invalid and the client cannot proceed

See [Handshake](/protocol-spec/handshake).

### What if I request a capability the host doesn't support?

The host returns that capability with `enabled: false` in `accepted_caps`. If you try to use it anyway (e.g. call a tool when `tools` is disabled), you'll get an `A2EError` with code `capability_missing`.

---

## Sessions & State

### How do sessions work?

Each connection gets its own `Session` with an isolated executor and state. In HTTP mode, the `SessionManager` creates sessions on POST `/session` and wires SSE streams. Sessions are independent — one agent cannot access another's state.

### Can I persist session state?

Yes. A2E supports snapshot/restore. A session's state can be saved to disk or SQLite and later restored to resume from that point. This is useful for pausing long-running tasks or recovering from crashes.

### What about audit logging?

Every plugin handler records an `AuditEntry` with timing, byte sizes, and success/error status. Audit is best-effort — it never crashes the handler. You can configure rotation (10 MB max, 5 backup files). See [Audit System](/sdk-reference/audit).

---

## Plugins

### How do I write a custom plugin?

Extend `A2EPlugin`, implement `handle()` for your message types, and declare them in `supported_messages()`. See [Writing a Plugin](/cookbook/writing-a-plugin) for a complete walkthrough.

### Can I have multiple plugins for the same capability?

Yes. Multiple plugins can serve the same capability. Dispatch is priority-based — plugins with higher `priority` values are called first. If a plugin is `exclusive=True`, it gets sole handling.

### How do I register a plugin?

Add it to `config.yaml` under the `plugins` list:

```yaml
plugins:
  - name: mytools
    type: tools
    cls: mypackage.MyToolPlugin
    metadata:
      enabled: true
```

The host dynamically imports the class at startup.

### Can plugins access other capabilities?

Plugins are isolated by design. Each plugin handles its own message types. If you need cross-capability logic, use the `chains` capability to compose a pipeline, or implement coordination at the agent level.

---

## Memory

### What are the three memory tiers?

| Tier | Purpose | Persistence |
|------|---------|-------------|
| **Working** | Short-term scratchpad for current task | Session-scoped |
| **Episodic** | Timestamped event log | Persistent across sessions |
| **Semantic** | Searchable knowledge base | Persistent, with TTL and tags |

### When should I use which tier?

- **Working** — Current conversation context, temporary variables, scratch calculations
- **Episodic** — "What happened when" — event timelines, interaction logs, audit trails
- **Semantic** — "What do I know about X" — facts, preferences, learned knowledge

### Can memory entries expire?

Yes. Set a `ttl` (time-to-live) in seconds on any memory entry. After the TTL elapses, the entry is considered expired and may be garbage-collected by the memory plugin.

---

## Tools & Toolkits

### What's the difference between tools and toolkits?

- **Tools** are individual callable functions with input/output schemas
- **Toolkits** are bundles of related tools with shared configuration (like a database connection string that multiple tools use)

### How do I expose an MCP server's tools?

Use the `mcp` capability. Configure an MCP server connection, and its tools are automatically proxied as A2E tools. See [MCP Integration](/cookbook/mcp-integration).

---

## Error Handling

### How should I handle errors?

```python
try:
    result = client.rpc(request, timeout=10)
except A2EClientError as e:
    if e.retryable:
        # Exponential backoff retry
        retry_with_backoff(request)
    else:
        # Fix the request, don't retry
        handle_permanent_error(e)
```

See [Error Codes](/protocol-spec/error-codes) for the full list.

### What errors are retryable?

| Code | Retryable | Strategy |
|------|-----------|----------|
| `runtime_error` | Yes | Exponential backoff |
| `timeout` | Yes | Increase timeout, then retry |
| `out_of_memory` | Yes | Back off and retry |
| `sandbox_crash` | Yes | Retry once |
| `parse_error` | No | Fix message format |
| `unauthorized` | No | Fix auth_token |
| `version_mismatch` | No | Update protocol version |
| `schema_violation` | No | Fix message structure |

---

## Performance

### How many concurrent RPCs can I make?

The `max_parallel` value in the handshake response (default: 4) indicates the maximum concurrent RPCs the host supports. Exceeding this may result in queuing or errors.

### Is DirectTransport faster than HTTP?

Yes, significantly. DirectTransport uses in-process queues with zero network overhead. Use it for RL step loops, testing, and any scenario where client and server are in the same process.

### How do I scale A2E?

A2E is designed for single-host deployments currently. For scaling:
- Run multiple host instances behind a load balancer
- Use session affinity (sticky sessions) for HTTP mode
- For stateless workloads, distribute agent connections across hosts

---

## Compatibility

### Which LLM providers work with A2E?

A2E is LLM-agnostic. Any LLM that can make function/tool calls or follow structured instructions can drive an A2E client. The protocol doesn't depend on a specific provider.

### Can I use A2E with existing MCP servers?

Yes. The `mcp` capability bridges MCP servers into A2E. You configure MCP server connections, and their tools/resources/prompts are automatically available through the A2E protocol. See [MCP Bridge](/cookbook/mcp-bridge).

### Does A2E work with LangChain / AutoGen / CrewAI?

A2E is a standalone protocol, but you can build adapter layers. An A2E client can be wrapped as a LangChain tool, or an AutoGen agent can use `A2EClient` as its environment interface.

