# Client API

## A2EClient

Transport-agnostic client for connecting to an A2E host.

### Constructor

```python
A2EClient(
    transport: BaseTransport,
    logger: logging.Logger,
    agent_id: str = "agent",
    auth_token: str = "",
    agent_caps: list[str] = None,
    type_registry: dict = None
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `transport` | `BaseTransport` | required | The transport to use (HTTP or Direct) |
| `logger` | `Logger` | required | Logger instance |
| `agent_id` | `str` | `"agent"` | Agent identifier sent during handshake |
| `auth_token` | `str` | `""` | Authentication token |
| `agent_caps` | `list[str]` | `None` | Requested capability names (e.g. `["tools", "memory"]`) |
| `type_registry` | `dict` | `None` | Initial type registry (merged with base types) |

### Lifecycle

```python
from a2e.core.client.client import A2EClient
from a2e.core.transports import build_transport

transport = build_transport(config.transport)
client = A2EClient(transport, logger, agent_id="my-agent", agent_caps=["tools", "memory"])

# Connect (starts transport + performs handshake)
client.connect()

# ... use client for RPC calls ...

# Disconnect (sends shutdown + stops transport)
client.disconnect()
```

**Context manager** support:

```python
with A2EClient(transport, logger, agent_caps=["tools"]) as client:
    result = client.rpc(my_request)
```

### Handshake

`connect()` internally calls `_handshake()` which:
1. Starts the transport
2. Sends a `HandshakeRequest` with `agent_id`, `agent_caps`, `auth_token`
3. Validates the `HandshakeResponse` (checks `ok` field)
4. Stores `session_id` and `accepted_caps`
5. Builds `_capability_map` for capability lookup

### RPC

```python
response = client.rpc(
    request,                    # A2EMessage subclass
    timeout=30.0,              # Seconds to wait
    event_callback=None        # Called for each A2EEvent before final response
)
```

How it works:
1. Encodes request to compact JSON and sends via transport
2. Creates a `queue.Queue` keyed by `req_id`
3. Polls the queue (1s intervals) until response or timeout
4. Incoming `A2EEvent` messages are routed to `event_callback`
5. `A2EError` responses raise `A2EClientError`
6. Successful responses are decoded via type registry and returned

### Ping

```python
latency_ms = client.ping()
```

Sends a `ping` message and measures round-trip time in milliseconds.

### Encoding/Decoding

```python
# Encode a message to compact JSON bytes
data = client.encode(message)

# Decode a JSON line to a Pydantic model
message = client.decode(line)
```

Decoding looks up the `type` field in the type registry. If found, the message is validated against the corresponding Pydantic model. Otherwise, it falls back to a generic `A2EMessage`.

### Type Registry Extension

```python
from a2e.caps.tools.protocol import TOOL_TYPE_MAP

client.update_msg_types(TOOL_TYPE_MAP)
```

Merges new type mappings into the client's type registry, enabling proper decoding of capability-specific messages.

### Push Handlers

Unsolicited server-initiated messages (`EnvStatePush`, `ProcReadEvent`, `MCPServerPush`) that arrive outside any pending RPC are routed via registered push handlers:

```python
def register_push_handler(self, msg_type: str, callback: Callable):
    """Register a callback for unsolicited push messages of a given type."""

def unregister_push_handler(self, msg_type: str, callback: Callable):
    """Remove a previously registered push handler."""
```

When an inbound message has no matching `req_id` in the pending or event maps, the client checks `_push_handlers[msg.type]` and dispatches to all registered callbacks.

Capability API classes (e.g. `EnvAPI`, `ProcsAPI`) use this internally. Direct usage is rarely needed but available:

```python
client.register_push_handler("env/state_push", lambda msg: print(f"Push: {msg.state_delta}"))
client.unregister_push_handler("env/state_push", my_handler)
```

### Incoming Message Routing

The `_on_message()` method dispatches each incoming message through three ordered paths:

1. **Pending RPC** — `req_id` matches an in-flight `rpc()` call → delivered to the response queue
2. **Event callback** — `req_id` matches registered event callbacks (from `rpc(..., event_callback=fn)`) → each callback invoked
3. **Push handler** — message type matches a registered push handler → callbacks invoked

### Capabilities

```python
caps = client.capabilities()  # Returns list of accepted Capability objects
```

Returns the `accepted_caps` from the handshake response.

## A2EClientError

Raised when the server returns an `A2EError`:

```python
class A2EClientError(Exception):
    code: str                    # A2EErrorCode value
    message: str                 # Human-readable description
    retryable: bool              # Whether to retry
    detail: dict                 # Structured context
    capability_name: str         # Which capability failed
    req_id: str                  # The failed request ID
    events: list[A2EEvent]       # Events collected before error
```

### Usage Example

```python
from a2e.core.client.client import A2EClient, A2EClientError

with client:
    try:
        result = client.rpc(tool_call_req, timeout=10.0)
    except A2EClientError as e:
        if e.retryable:
            # Retry logic
            result = client.rpc(tool_call_req, timeout=30.0)
        else:
            print(f"Fatal error: {e.code} - {e.message}")
```
