# Server API

```text
a2e/core/server/server.py          — A2EServer
a2e/core/server/executor.py       — A2EServerRuntimeExecutor
a2e/core/server/session.py        — Session
a2e/core/server/session_manager.py — SessionManager
```

## A2EServer

Top-level server that manages sessions, loads plugins, and routes messages.

### Constructor

```python
A2EServer(config: A2EHostConfig)
```

### start()

Returns either a FastAPI app (HTTP mode) or a `DirectTransport` (direct mode), based on `config.transport.type`:

```python
server = A2EServer(config)
app = server.start()  # HTTP mode -> FastAPI app
# OR
transport = server.start()  # Direct mode -> DirectTransport for client use
```

### HTTP Mode (FastAPI)

When transport type is `"http"`, `start()` returns a FastAPI app with these routes:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/session` | Create a new session, returns `session_id` |
| POST | `/send` | Send a message body to a session (header: `X-Session-Id`) |
| GET | `/stream` | SSE endpoint yielding session responses |
| GET | `/health` | Health check |

```python
import uvicorn
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer

config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
app = server.start()

uvicorn.run(app, host=config.server.host, port=config.server.port)
```

### Direct Mode

Creates two paired `DirectTransport` instances with two `A2EServerRuntimeExecutor` instances:

```python
server = A2EServer(config)
client_transport = server.start()  # DirectTransport

# Use client_transport with A2EClient
client = A2EClient(client_transport, logger, agent_caps=["tools"])
client.connect()
```

## A2EServerRuntimeExecutor

Per-session message processing engine. Each session gets its own executor instance.

### Plugin Loading

```python
def _load_plugins(self):
    for plugin_config in self.config.plugins:
        if not plugin_config.metadata.enabled:
            continue
        # Dynamic import: "a2e.caps.tools.plugin" -> ToolPlugin
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        plugin = cls()
        plugin.setup(self, {
            **plugin_config.metadata.model_dump(),
            "audit_log": self.audit_log,
            "session_id": self.session_id
        })

    # Wire push callback for plugins that support async events
    if hasattr(plugin, 'set_push_callback'):
        plugin.set_push_callback(self._send)
```

### Type Registry Building

```python
def _build_registry(self):
    for plugin in self._plugin_registry.all():
        for msg_type, model_class in plugin.supported_messages().items():
            self.type_registry[msg_type] = model_class
            self.type_to_plugins[msg_type].append(plugin)
    # Sort each list by priority (descending)
```

### Capability Negotiation

```python
def _negotiate_caps(self, agent_caps: list[str]):
    for cap_name in agent_caps:
        plugins = self._cap_registry.get(cap_name)
        if plugins:
            accepted.append(Capability(capability=cap_name, enabled=True, ...))
```

### Message Dispatch Flow

```
1. Raw NDJSON line arrives via transport
2. handle_raw(line):
   a. Decode via type_registry -> Pydantic model
   b. Check if core message (handshake, ping, shutdown) -> _handle_core()
   c. Non-core -> submit to ThreadPoolExecutor -> _dispatch()
3. _dispatch(model):
   a. Look up plugins by model.type
   b. If exclusive: run highest-priority plugin only
   c. If broadcast: run all plugins sorted by priority
   d. Collect response, send back via transport
```

### Error Handling

If any step fails (decode error, plugin exception, etc.), the executor constructs an `A2EError` and sends it back:

```python
def _safe_send_error(self, req_id, code, message, **kwargs):
    error = A2EError(req_id=req_id, code=code, message=message, **kwargs)
    self._send(error)
```

## ThreadPoolExecutor

Non-core messages are dispatched to a `ThreadPoolExecutor` for concurrent handling. The `max_workers` parameter comes from `config.global_limits.max_workers` (default varies by Python version).

This means:
- Multiple `tool/call/req` messages can be processed in parallel
- The handshake/ping/shutdown path stays on the main thread for responsiveness
- Plugin handlers must be thread-safe
