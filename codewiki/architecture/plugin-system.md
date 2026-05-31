# Plugin System

```text
a2e/core/plugins/interface.py  — A2EPlugin ABC
a2e/core/plugins/registry.py   — PluginRegistry
a2e/core/plugins/schema.py     — PluginConfig, PluginMeta
a2e/core/server/executor.py    — Dynamic loading + dispatch
a2e/core/capabilities.py       — CapabilityRegistry
```

## Overview

A2E is a **plugin-centric runtime**. The host (server) is a thin execution kernel that loads, routes, and manages lifecycle. All capability-specific logic lives in plugins that are dynamically loaded from configuration.

## A2EPlugin Interface

```mermaid
classDiagram
    class A2EPlugin {
        <<abstract>>
        +name: str
        +type: str
        +priority: int
        +exclusive: bool
        +setup(host_instance, config)
        +supported_messages() Dict
        +handle(message) A2EMessage
        +caps_metadata() dict
        +emit_event(event) void
        +save_state(store, key, session_id)
        +restore_state(store, key, session_id)
        +teardown()
        +audit_handle(msg, response, req_id, t0)
    }

    class ToolPlugin {
        +name = "base_tool"
        +_list_tools() List~ToolDefinition~
        +_execute_tool(name, args) Dict
    }

    class MemoryPlugin {
        +on_store(entries) tuple
        +on_retrieve(req) entries
        +on_forget(req) deleted
    }

    class EnvPlugin {
        +name = "base_env"
        +on_reset(seed, options) EnvState
        +on_step(episode_id, action) tuple
        +on_close()
    }

    A2EPlugin <|-- ToolPlugin
    A2EPlugin <|-- MemoryPlugin
    A2EPlugin <|-- EnvPlugin
```

### Class-Level Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | — | Unique plugin instance name |
| `type` | `str` | — | Capability type (matches `A2ECapability` enum) |
| `priority` | `int` | `0` | Higher = runs first in dispatch |
| `exclusive` | `bool` | `False` | If True, only this plugin handles its message types |

### Lifecycle Methods

| Method | Purpose |
|--------|---------|
| `setup(host_instance, config)` | Called at load time. Receives host reference and config dict. Extracts `audit_log` and `session_id` from config. |
| `supported_messages()` | **Abstract**. Returns `Dict[str, Type[BaseModel]]` mapping type strings to Pydantic model classes. |
| `handle(message)` | **Abstract**. Processes a decoded message, returns response `A2EMessage` or `None`. |
| `caps_metadata()` | Returns `{name, type, priority, exclusive}` for capability negotiation. |
| `emit_event(event)` | Sends an async event to the client through the host executor. Standard path for all server-initiated events. |
| `save_state(store, key, session_id)` | Serializes plugin state to `SnapshotStore` under key `"plugin_name:key"`. |
| `restore_state(store, key, session_id)` | Restores from `SnapshotStore`. |
| `teardown()` | Lifecycle cleanup on shutdown. |

### Audit Integration

Every plugin handler should call `audit_handle(msg, response, req_id, t0)` after processing. This constructs an `AuditEntry` with:
- Timing: `duration_ms` from `t0`
- Byte sizes: `input_bytes`, `output_bytes`
- Success/error: `success` bool, `error_code` if failed

Audit failures are **caught and printed** — they never crash the plugin.

## Event Emission (Plugin → Client)

Plugins can send asynchronous events to the client at any time via `emit_event()`:

```python
# a2e/core/plugins/interface.py
class A2EPlugin(ABC):
    def emit_event(self, event: A2EMessage):
        """Send an async event to the client through the host executor."""
        host = getattr(self, 'host_instance', None)
        if host and hasattr(host, '_send'):
            host._send(event)
```

This is the **standard path** for all server-initiated events (streaming output, progress updates, partial results). It routes through the executor's `_send()` method, which encodes and delivers the event via the transport.

### How it works

```mermaid
sequenceDiagram
    participant Plugin as Plugin
    participant Executor as A2EServerRuntimeExecutor
    participant Transport
    participant Client as A2EClient

    Plugin->>Executor: emit_event(ProcReadEvent)
    Executor->>Executor: encode(event) → JSON
    Executor->>Transport: send(JSON line)
    Transport->>Client: incoming JSON
    Client->>Client: decode → A2EMessage
    Client->>Client: route:
    Note over Client: Pending RPC match?<br/>→ deliver to queue<br/>Active event callback?<br/>→ call event_callback<br/>Unsolicited push?<br/>→ call push_handler
```

### Client-side routing

The `A2EClient._on_message()` dispatches each incoming message through three paths in order:

1. **Pending RPC match** — if `req_id` matches an in-flight RPC, the message is delivered to its result queue.
2. **Event tied to an active RPC** — if `req_id` has registered event callbacks (via `rpc(..., event_callback=fn)`), each callback is invoked.
3. **Unsolicited push** — if the message type has registered push handlers (via `register_push_handler()`), those handlers are called.

The third path enables capability APIs to subscribe to server-initiated messages that arrive outside any RPC context — for example `EnvStatePush`, `ProcReadEvent`, or `MCPServerPush`.

See [Client API](/sdk-reference/client-api#push-handlers) for the push handler API.

## Plugin Configuration

```yaml
plugins:
  - name: mytools          # Unique instance name
    type: tools             # Capability type
    cls: a2e.caps.tools.plugin.ToolPlugin  # Import path
    metadata:
      enabled: true
      priority: 0
      exclusive: false
      # ... plugin-specific config ...
```

**PluginConfig** fields:
| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique instance name |
| `type` | `str` | Capability type string |
| `cls` | `str` | Dot-path import string |
| `metadata` | `PluginMeta` | `enabled`, `priority`, `exclusive` + extra fields |

## Dynamic Loading

The executor loads plugins at startup via `importlib`:

```python
# A2EServerRuntimeExecutor._load_plugins()
for plugin_config in config.plugins:
    if not plugin_config.metadata.enabled:
        continue
    module_path, class_name = plugin_config.cls.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    plugin = cls()
    plugin.setup(self, plugin_config.metadata.model_dump())
    self._plugin_registry.register(plugin)

# Wire push callback for plugins that support async events
for name, plugin in self._plugin_registry.all():
    if hasattr(plugin, 'set_push_callback'):
        plugin.set_push_callback(self._send)
```

## Type Registry Building

After loading, each plugin's `supported_messages()` populates two structures:

```python
# type_registry: msg_type -> Pydantic model class
# type_to_plugins: msg_type -> sorted list of plugins (by priority)
```

This enables the executor to decode incoming NDJSON by looking up the model class, then route to the correct plugin(s).

## Message Dispatch

```mermaid
flowchart LR
    M[Raw NDJSON line] --> D[Decode via type_registry]
    D --> C{Core message?}
    C -->|Yes| H[Handle core: handshake/ping/shutdown]
    C -->|No| T[Thread pool dispatch]
    T --> E{Exclusive?}
    E -->|Yes| P1[Single highest-priority plugin]
    E -->|No| P2[Broadcast to all plugins sorted by priority]
```

- **Exclusive mode**: Only the highest-priority plugin handles the message
- **Broadcast mode**: All registered plugins handle the message, sorted by priority
- Non-core messages are dispatched to a `ThreadPoolExecutor` for concurrent handling

## Plugin Registries

| Registry | Purpose | Key |
|----------|---------|-----|
| `PluginRegistry` | Name -> plugin instance | Plugin `name` |
| `CapabilityRegistry` | Capability string -> list of plugins | `A2ECapability` value |

The `CapabilityRegistry` is used during handshake to match agent-requested capabilities against loaded plugins.
