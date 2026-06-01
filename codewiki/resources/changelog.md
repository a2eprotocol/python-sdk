# Changelog

All notable changes to the A2E protocol and SDK are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.2] — 2026-06-01

### Removed

- Experimental subprocess transport prototype (`a2e/experimental/core/transports/subprocess.py`) — fully replaced by the core `a2e/core/transports/subprocess.py` since v0.1.1; the experimental directory is now removed

## [0.1.1] — 2026-06-01

### Added

**Transport**
- `SubprocessTransport` promoted from experimental to core (`a2e/core/transports/subprocess.py`) — spawns host as subprocess, communicates via stdin/stdout NDJSON
- `SubprocessTransportConfig.env` and `cwd` fields for environment/working dir control
- `SubprocessTransport` and `DirectTransportConfig`/`SubprocessTransportConfig` exported in `__all__`

**Cookbook**
- `cookbook/agents/direct_agent.py` — agent connecting via DirectTransport pair with `--self-contained` mode
- `cookbook/agents/subprocess_agent.py` — agent that launches host as subprocess over SubprocessTransport
- `cookbook/servers/a2e_subprocess_host.py` — host that reads stdin via DirectTransport bridge
- `cookbook/servers/config_subprocess.yaml` — standalone subprocess transport config example

### Fixed

- **DirectTransport.send()**: Now falls back to `_out_queue.put(msg)` when `_out_handler` is None, making `connect()` wiring actually work. Previously all outgoing messages were silently dropped when no `_out_handler` was set (the server direct mode case).
- **Client rpc() event loop**: Added missing `continue` after processing `A2EEvent` messages — previously events fell through and were returned as the final RPC response instead of waiting for the actual response.
- **Executor _build_registry()**: Added `type_to_plugins.clear()` before rebuild to prevent duplicate plugin registration entries when `_build_registry()` is called multiple times.
- **Capability enum**: Added `TEST = "test"` to `A2ECapability` for generic test capability.

---

## [0.1.0] — 2026-05-18

### Added

**Protocol**
- NDJSON-based message protocol with `A2EMessage` base model (`type`, `id`, `a2e`, `ts`)
- Handshake flow: `handshake/req` / `handshake/resp` with authentication and capability negotiation
- Capability negotiation: `agent_caps` → `accepted_caps` matching against loaded plugins
- `A2EError` message format with `code`, `message`, `detail`, `retryable`, `capability_name`
- Core error codes: `parse_error`, `runtime_error`, `invalid_message`, `version_mismatch`, `unauthorized`, `schema_violation`, `timeout`, `out_of_memory`, `sandbox_crash`
- Protocol version `1.0`

**Capabilities — 9 Namespaces**
- **Tools** (`tools`): `tool/list`, `tool/call`, `tool/event` — named functions with JSON Schema I/O, streaming events
- **Memory** (`memory`): `memory/store`, `memory/recall`, `memory/forget`, `memory/search` — 3-tier storage (working, episodic, semantic) with TTL, tags, and full-text search
- **Environment** (`env`): `env/reset`, `env/step`, `env/observe`, `env/reward` — RL environment primitives with action space validation
- **Processes** (`proc`): `proc/spawn`, `proc/write`, `proc/read`, `proc/signal`, `proc/kill` — long-running subprocess management with command allowlist, `shell=False`, and process quotas
- **Learning** (`learn`): `learn/feedback`, `learn/experience`, `learn/adapt`, `learn/stats` — feedback (POSITIVE/NEGATIVE/NEUTRAL/CORRECTIVE), experience tuples, UCB1 adaptation
- **Skills** (`skills`): `skill/discover`, `skill/call`, `skill/list` — named, versioned execution units with `input_schema`, `output_schema`, and optional Docker sandboxing
- **Toolkits** (`toolkits`): `toolkit/list`, `toolkit/install`, `toolkit/configure`, `toolkit/uninstall` — tool bundles with shared JSON Schema configuration and lifecycle management
- **Chains** (`chains`): `chain/execute`, `chain/validate` — DAG pipelines with `action`, `branch`, `map`, `gather`, `reduce` node kinds, cycle detection, and timeout enforcement
- **MCP** (`mcp`): `mcp/connect`, `mcp/disconnect`, `mcp/call_tool`, `mcp/read_resource`, `mcp/get_prompt`, `mcp/list_tools` — Model Context Protocol bridge proxying external MCP servers

**Subagents**
- `subagent/spawn`, `subagent/cancel`, `subagent/list` — child agent spawning with `shared`, `restricted`, `isolated`, and `snapshot` memory scopes
- Depth limiting, step limiting, timeout enforcement, and cancellation propagation

**Runtime**
- `A2EServer` — FastAPI-based server with session-per-connection model
- `A2EClient` — RPC client with queue-based request correlation and event streaming via `event_callback`
- `A2EServerRuntimeExecutor` — dispatch core routing messages to plugins via type registry
- `PluginRegistry` — maps message types to plugin handlers, supports priority-based and exclusive dispatch
- `SessionManager` — creates and tracks isolated sessions in HTTP mode

**Transport**
- `HTTPTransport` — POST `/send` + GET `/stream` (SSE) with session management and reconnection
- `DirectTransport` — in-process cross-wired queues for testing and RL step loops
- `BaseTransport` ABC with `start()`, `send()`, `deliver()`, handler slots

**Audit**
- `AuditLog` — thread-safe structured audit logging for all plugin handler invocations
- `AuditEntry` — records `ts`, `session_id`, `req_id`, `success`, `duration_ms`, `error_code`, `input_bytes`, `output_bytes`
- `RotatingFileHandler` — 10 MB max file size, 5 backup files, JSONL format
- `build_audit_log()` and `build_session_id()` factory functions

**Persistence**
- File-based and SQLite storage backends for session snapshot/restore
- `SnapshotStore` interface for pluggable persistence

**Experimental**
- `SubprocessTransport` — stdin/stdout transport for host subprocess communication

**Configuration**
- `A2EHostConfig` — Pydantic v2 configuration model loaded from YAML
- Plugin configuration with `name`, `type`, `cls`, `metadata`
- Audit configuration: `enabled`, `path`, `rotate`, `session_id_source`
- Transport configuration: `type` (http / direct)

**Cookbook**
- `Writing a Plugin` — step-by-step plugin development guide
- `Environment Agent Loop` — RL step loop patterns with DirectTransport
- `Chain Pipeline` — DAG pipeline construction and execution
- `MCP Integration` — connecting external MCP servers
- `MCP Bridge (Plugin & Client)` — full WSMCPConnection transport adapter implementation
- `Memory (Plugin & Client)` — SQLiteMemoryPlugin with TTL, tags, and agent loop pattern
- `Custom Tools (Plugin & Client)` — HTTPToolsPlugin with streaming events and correlation IDs
- `Toolkit Builder (Plugin & Client)` — DatabaseToolkitPlugin with PostgreSQL toolkit and JSON Schema config

**Documentation**
- VitePress documentation site (`codewiki/`) with 7 sections: Getting Started, Architecture, SDK Reference, Capabilities, Protocol Specification, Cookbook, Resources
- Architecture Overview with three-layer design, system diagram, and key patterns
- Protocol Specification: Message Format, Handshake, Capability Negotiation, Message Types, Error Codes
- Capability-specific protocol specs for all 9 namespaces + subagents
- SDK Reference: Client API, Server API, Configuration, Audit System, Persistence

**Resources**
- Glossary — A-Z reference of 40+ A2E terms and concepts
- FAQ — 30+ frequently asked questions across 10 categories
- Security & Trust — trust model, authentication, transport security, per-capability security tables, threat model, plugin security checklist
- Support — troubleshooting guide, debugging techniques, contribution guidelines

---

## [0.1.0-dev] — 2026-05-13

### Added

**Core Runtime**
- `A2EEvent` message model replacing `InvokeEvent` for progressive streaming
- Event streaming support in client `rpc()` with `event_callback`
- Audit logging system: `AuditLog`, `AuditEntry`, `RotatingFileHandler`
- Audit configuration in `A2EHostConfig`

**Capabilities**
- Memory plugin with 3-tier storage (working, episodic, semantic)
- Learning plugin with feedback, experience, and UCB1 adaptation
- Proc plugin with subprocess management and command allowlist
- Skills plugin with sandboxed execution and `input_schema` validation
- Toolkits plugin with JSON Schema configuration and lifecycle management
- MCP plugin with tool/resource/prompt proxying

**Transport**
- HTTPTransport with POST `/send` and GET `/stream` (SSE)
- DirectTransport for in-process testing

**Experimental**
- SubprocessTransport for host subprocess communication

---

## [0.1.0-alpha] — 2026-04-30

### Added

**Initial Release**
- NDJSON-based message protocol with `A2EMessage` base model
- Handshake flow with `auth_token` authentication
- Capability negotiation between agent and host
- 9 capability namespaces: tools, memory, env, proc, learn, skills, toolkits, chains, mcp
- Plugin system: `A2EPlugin` ABC with `setup()`, `handle()`, `supported_messages()`
- `PluginRegistry` with priority-based and exclusive dispatch
- `A2EServer` with FastAPI backend and session-per-connection model
- `A2EClient` with RPC and queue-based request correlation
- `BaseTransport` ABC with HTTP and Direct implementations
- Session management with isolated executors per connection
- File-based and SQLite persistence for snapshot/restore
- `A2EHostConfig` loaded from YAML with plugin, transport, and audit sections

---

## Release Notes Format

Each release entry contains the following sections where applicable:

| Section | Description |
|---------|-------------|
| **Added** | New features, capabilities, and APIs |
| **Changed** | Changes to existing functionality |
| **Deprecated** | Features to be removed in future releases |
| **Removed** | Features removed in this release |
| **Fixed** | Bug fixes |
| **Security** | Security-related changes and fixes |

---

## Version Compatibility

| A2E Version | Protocol | Python | Pydantic | FastAPI | MCP |
|-------------|----------|--------|----------|---------|-----|
| 0.1.x | 1.0 | 3.10+ | v2 (2.12+) | 0.135+ | 1.27+ |

---

## Upgrade Guide

### Upgrading from alpha to 0.1.0

1. **Event model renamed**: `InvokeEvent` → `A2EEvent`. Update any client code that references the old model name.
2. **Audit logging**: Audit is now enabled by default. Add `audit` section to your `config.yaml` or explicitly set `enabled: false`.
3. **Client API paths**: Some internal module paths were reorganized. Update imports:
   - `a2e.agent` → `a2e.core.client.client`
   - Cookbook modules moved from `cookbook/` to `cookbook/servers/`
4. **Event streaming**: The `rpc()` method now supports `event_callback` for progressive streaming. Existing code without callbacks continues to work.
5. **Proc plugin**: Command allowlist is now enforced. Previously all commands were allowed. Add allowed commands to your plugin config.

### General Upgrade Steps

1. Update the package: `pip install --upgrade a2e`
2. Check the changelog for breaking changes
3. Update `config.yaml` if new configuration fields are required
4. Ensure client and server use the same protocol version
5. Run the test suite to verify compatibility
