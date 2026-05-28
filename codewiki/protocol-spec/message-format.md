# Message Format

```text
a2e/caps/base/protocol.py — A2EMessage, MessageType, A2E_BASE_TYPE_MAP
```

## Specification Version

**A2E Protocol Version 1.0** — a strict superset of SCP (Skill Call Protocol) 1.0.

## Framing

Messages are transmitted as **NDJSON** (newline-delimited JSON) over a reliable byte stream. Each message is a single JSON object on one line, terminated by `\n`.

```
<JSON object>\n
<JSON object>\n
...
```

Compact JSON encoding is used — no extraneous whitespace.

## Base Message Schema

Every A2E message conforms to this base schema:

```json
{
  "a2e": "1.0",
  "type": "<namespace>/<verb>",
  "id": "<uuid-hex>",
  "ts": <unix-epoch-float>
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `a2e` | `string` | Yes | Protocol version, always `"1.0"` |
| `type` | `string` | Yes | Message type identifier (e.g. `"tool/call/req"`) |
| `id` | `string` | Yes | UUID hex, unique per message |
| `ts` | `number` | Yes | Unix epoch timestamp (float, seconds) |

Capability-specific messages add additional fields.

## Type String Convention

Type strings follow the pattern: `<namespace>/<verb>` or `<namespace>/<verb>/<suffix>`

| Pattern | Example | Meaning |
|---------|---------|---------|
| `<ns>/<verb>/req` | `tool/call/req` | Request from agent |
| `<ns>/<verb>/resp` | `tool/call/resp` | Response from host |
| `<ns>/<verb>` | `chain/event` | Event or notification |
| `<ns>/<verb>/<action>` | `mcp/server/register/req` | Nested namespace |

## Encoding Rules

1. **UTF-8** encoding for all text
2. **Compact JSON** — no extra whitespace
3. **No binary framing** — newline delimits messages
4. **Pydantic v2** validation on both sides — invalid messages produce `A2EError` with `schema_violation` code

## Decoding

The receiver maintains a **type registry** mapping type strings to Pydantic model classes:

```python
# Base types (always registered)
A2E_BASE_TYPE_MAP = {
    "handshake/req":  HandshakeRequest,
    "handshake/resp": HandshakeResponse,
    "invoke/event":   A2EEvent,
    "ping":           Ping,
    "pong":           Pong,
    "shutdown":       Shutdown,
    "error":          A2EError,
}

# Plugin types (registered at startup)
TOOL_TYPE_MAP = {
    "tool/list/req":  ToolListRequest,
    "tool/list/resp": ToolListResponse,
    "tool/call/req":  ToolCallRequest,
    "tool/call/resp": ToolCallResponse,
    "tool/event":     ToolEvent,
}
```

If a type string is not found in the registry, the message is decoded as a generic `A2EMessage` (graceful degradation).

## Message Ordering

- **Within a session**: Messages are processed in order of arrival
- **Across sessions**: No ordering guarantee
- **Events**: Each `A2EEvent` has a monotonic `seq` number within its `req_id` scope
- **Correlation**: Responses reference their request via `req_id`

## Size Limits

No explicit message size limit is defined in the protocol. Implementations may impose limits via `global_limits` configuration.

## Extensibility

New capability namespaces can be added by:
1. Defining new `MessageType` enum values
2. Creating Pydantic request/response/event models
3. Building a `TYPE_MAP` dict
4. Implementing an `A2EPlugin` subclass

Unknown message types degrade gracefully — they are decoded as `A2EMessage` and can be routed to a catch-all handler.
