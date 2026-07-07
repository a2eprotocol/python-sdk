# Writing a Plugin

## Overview

All A2E capabilities are implemented as plugins. This guide shows you how to write a custom plugin from scratch.

## A2EPlugin ABC

Every plugin inherits from `A2EPlugin`:

```python
from a2e.core.plugins.interface import A2EPlugin

class MyPlugin(A2EPlugin):
    name = "my_plugin"       # Unique identifier
    type = "custom"          # Capability type
    priority = 0             # Dispatch priority (higher = preferred)
    exclusive = False        # True = sole handler for its message types

    # --- Required methods ---
    def supported_messages(self) -> dict[str, type]:
        """Return {type_string: PydanticModelClass} mapping"""

    def handle(self, msg) -> A2EMessage | None:
        """Main message handler"""

    # --- Event emission ---
    def emit_event(self, event):
        """Send async event to client via host executor"""

    # --- Lifecycle hooks ---
    def setup(self, host, config: dict):
        """Called once when plugin is loaded. Config includes:
        - audit_log: AuditLog instance
        - session_id: Session identifier
        - All metadata fields from PluginConfig"""

    def teardown(self):
        """Called when plugin is unloaded"""

    # --- State persistence ---
    def save_state(self, store, key, session_id):
        """Persist plugin state to SnapshotStore"""

    def restore_state(self, store, key, session_id):
        """Restore plugin state from SnapshotStore"""

    def clear_state(self, store, key, session_id):
        """Clear persisted state"""

    # --- Audit ---
    def audit_handle(self, msg, response, req_id, t0):
        """Record audit entry (best-effort, never crashes)"""
```

## Complete Example: Counter Environment Plugin

The SDK provides capability-specific abstract base plugins. For environments, extend `EnvPlugin` (`a2e.caps.env.plugin`) which handles all message routing, episode lifecycle, and persistence — you only implement the abstract hooks:

```python
from a2e.caps.env.plugin import EnvPlugin
from a2e.caps.env.protocol import (
    EnvAction, EnvObservation, EnvState,
)

class CounterEnv(EnvPlugin):
    name = "counter_env"

    def __init__(self, host_instance, config):
        super().__init__(host_instance, config)
        self._target = 10

    # --- Required hooks ---

    def on_reset(self, seed=None, options=None) -> EnvState:
        """Called when environment is reset. No episode exists yet here."""
        self._target = int((options or {}).get("target", 10))
        return EnvState(count=0, step_num=0)

    def on_step(self, episode_id: str, action: EnvAction) -> EnvObservation:
        """Called on each step. Episode exists and is tracked by EnvPlugin."""
        prev = self._episode.state.model_dump()
        new_count = int(prev.get("count", 0))
        if action.action_type == "inc":
            new_count += action.payload.get("amount", 1)
        elif action.action_type == "dec":
            new_count -= action.payload.get("amount", 1)

        done = new_count >= self._target
        return EnvObservation(
            episode_id=episode_id,
            step_num=int(prev.get("step_num", 0)) + 1,
            state=EnvState(count=new_count, step_num=int(prev.get("step_num", 0)) + 1),
            reward=1.0 if done else 0.0,
            done=done,
        )
```

## Registering in Config

```yaml
plugins:
  - name: counter_env
    type: env
    cls: my_package.counter.CounterEnv
    metadata:
      enabled: true
      priority: 0
```

The `cls` field uses dotted module path notation. The executor dynamically imports it:

```python
# a2e/core/server/executor.py
mod = importlib.import_module("my_package.counter")
cls = getattr(mod, "CounterEnv")
plugin = cls()
plugin.setup(self, config)
```

## Plugin Priority & Dispatch

When multiple plugins handle the same message type:
- **Exclusive plugins** (`exclusive=True`): Only the highest-priority exclusive plugin runs
- **Non-exclusive plugins**: All matching plugins run, sorted by priority descending
- The executor collects all responses and returns the first non-None result

## Streaming Events

Plugins can emit streaming events to the client during long-running operations using the built-in `emit_event()` method:

```python
from a2e.caps.base.protocol import A2EEvent, EventKind
from a2e.caps.tools.protocol import ToolEvent

class MyStreamingPlugin(A2EPlugin):
    def handle(self, msg):
        # During execution, emit progress events
        self.emit_event(ToolEvent(
            kind="progress",
            data={"pct": 50, "message": "halfway"},
            req_id=msg.id,
        ))

        # Or use the generic A2EEvent
        self.emit_event(A2EEvent(
            kind=EventKind.PROGRESS.value,
            data={"pct": 100, "message": "done"},
            req_id=msg.id,
        ))

        return MyResponse(result="complete")
```

`emit_event()` routes through `self.host_instance._send()` — the executor serializes the event into NDJSON and delivers it via the transport. No callback registration needed.

### How the executor wires it

During plugin loading (`_load_plugins`), the executor calls `set_push_callback(self._send)` on any plugin that exposes it. This enables the legacy `plugin.push()` pattern (used by `EnvPlugin`). The modern `emit_event()` path is always available through the base class and does not require separate wiring.

### Client-side handling

Events arrive at the client and are routed via `A2EClient._on_message()` through three ordered paths:

1. **Pending RPC** — if `req_id` matches an in-flight `rpc()` call
2. **Event callback** — if `req_id` was registered via `rpc(..., event_callback=fn)`
3. **Push handler** — if the message type has a registered push handler

See [Client API → Push Handlers](/sdk-reference/client-api#push-handlers) for details.

## Testing Your Plugin

```python
import logging
from a2e.core.transports.direct import DirectTransport
from a2e.core.client.client import A2EClient
from a2e.core.server.executor import A2EServerRuntimeExecutor
from a2e.schema import A2EHostConfig
from a2e.core.plugins import PluginConfig
from a2e.core.transports import TransportConfig
from a2e.caps.env.client import EnvAPI

logger = logging.getLogger("test")

# Create a wired DirectTransport pair
host_t = DirectTransport(logger=logger)
client_t = DirectTransport(logger=logger)
host_t.connect(client_t)
client_t.connect(host_t)

# Build host config with the counter plugin
config = A2EHostConfig(
    host_id="test",
    server={"host": "0.0.0.0", "port": 0},
    transport={"type": "direct", "config": {}},
    audit={"enabled": False},
    plugins=[PluginConfig(name="counter", type="env", cls="my_package.counter.CounterEnv")],
)

# Start the host executor on one side
executor = A2EServerRuntimeExecutor(config, host_t, logger)
executor.start()

# Connect the agent client on the other side
client = A2EClient(client_t, logger, agent_id="test-agent", agent_caps=["env"])
client.connect()

# Use the capability API
env = EnvAPI(client)
resp = env.reset(env_name="counter_env", seed=42)
print(f"Episode started: {resp.episode_id}")

# ... test steps ...
client.disconnect()
executor.stop()
```