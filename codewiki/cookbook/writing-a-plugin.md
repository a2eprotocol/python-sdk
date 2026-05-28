# Writing a Plugin

```text
a2e/core/plugins/interface.py — A2EPlugin ABC
```

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

## Complete Example: Counter Plugin

```python
from a2e.core.plugins.interface import A2EPlugin
from a2e.caps.env.protocol import (
    EnvResetRequest, EnvResetResponse,
    EnvStepRequest, EnvStepResponse,
    EnvObserveRequest, EnvObserveResponse,
    EnvCloseRequest, EnvCloseResponse,
    EnvAction, EnvObservation, EnvState,
)

class CounterEnv(A2EPlugin):
    name = "counter_env"
    type = "env"
    priority = 0

    def setup(self, host, config):
        super().setup(host, config)
        self._count = 0
        self._episode_id = ""

    def supported_messages(self):
        return {
            "env/reset/req": EnvResetRequest,
            "env/step/req": EnvStepRequest,
            "env/observe/req": EnvObserveRequest,
            "env/close/req": EnvCloseRequest,
        }

    def handle(self, msg):
        if isinstance(msg, EnvResetRequest):
            return self._reset(msg)
        elif isinstance(msg, EnvStepRequest):
            return self._step(msg)
        elif isinstance(msg, EnvObserveRequest):
            return self._observe(msg)
        elif isinstance(msg, EnvCloseRequest):
            return self._close(msg)
        return None

    def _reset(self, msg):
        self._count = 0
        self._episode_id = msg.episode_id or "ep_1"
        state = EnvState(count=self._count)
        return EnvResetResponse(
            episode_id=self._episode_id,
            observation=EnvObservation(
                episode_id=self._episode_id,
                step_num=0,
                state=state,
                done=False,
                reward=0.0
            )
        )

    def _step(self, msg):
        action = msg.action
        if action.action_type == "inc":
            self._count += action.payload.get("amount", 1)
        elif action.action_type == "dec":
            self._count -= action.payload.get("amount", 1)

        reward = 1.0 if self._count > 0 else -1.0
        done = self._count >= 10

        return EnvStepResponse(
            observation=EnvObservation(
                episode_id=self._episode_id,
                step_num=msg.step_num + 1,
                state=EnvState(count=self._count),
                done=done,
                reward=reward
            )
        )

    def _observe(self, msg):
        return EnvObserveResponse(
            observation=EnvObservation(
                episode_id=self._episode_id,
                state=EnvState(count=self._count),
                done=self._count >= 10
            )
        )

    def _close(self, msg):
        return EnvCloseResponse()

    def save_state(self, store, key, session_id):
        store.save(f"{self.name}:{key}", {"count": self._count})

    def restore_state(self, store, key, session_id):
        state = store.load(f"{self.name}:{key}")
        self._count = state.get("count", 0)
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

Plugins can emit streaming events during long-running operations:

```python
class MyToolPlugin(A2EPlugin):
    def setup(self, host, config):
        super().setup(host, config)
        self._emit_callback = None

    def set_event_callback(self, cb):
        self._emit_callback = cb

    def emit(self, kind, data):
        if self._emit_callback:
            event = ToolEvent(kind=kind, data=data, req_id=self._current_req_id)
            self._emit_callback(event)
```

The executor sets the callback before calling `handle()`:

```python
# executor.py
def _dispatch(self, model):
    for plugin in plugins:
        if hasattr(plugin, 'set_event_callback'):
            plugin.set_event_callback(self._send_callback)
        response = plugin.handle(model)
```

## Testing Your Plugin

```python
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.core.transports.direct import DirectTransport
from a2e.schema import A2EHostConfig

config = A2EHostConfig(
    host_id="test",
    plugins=[PluginConfig(name="counter", type="env", cls="my_package.counter.CounterEnv")],
    transport=TransportConfig(type="direct")
)

server = A2EServer(config)
transport = server.start()  # DirectTransport

client = A2EClient(transport, logger, agent_caps=["env"])
client.connect()

env = EnvAPI(client)
resp = env.reset(env_name="counter_env")
# ... test steps ...
client.disconnect()
```