# Error Codes

```text
a2e/caps/base/protocol.py — A2EErrorCode enum
a2e/caps/tools/protocol.py — ToolErrorCode
a2e/caps/skills/protocol.py — SkillErrorCode, ErrorCode
a2e/caps/chains/protocol.py — ChainErrorCode
a2e/caps/mcp/protocol.py  — MCPErrorCode
```

## A2EErrorCode (Core)

The base error codes returned in `A2EError` messages:

| Code | Description | Retryable |
|------|-------------|-----------|
| `parse_error` | Could not parse the NDJSON line | No |
| `runtime_error` | Generic runtime failure | Yes |
| `invalid_message` | Message structure is invalid | No |
| `version_mismatch` | Protocol version not supported | No |
| `unauthorized` | Authentication failed | No |
| `schema_violation` | Message failed Pydantic validation | No |
| `timeout` | Operation timed out | Yes |
| `out_of_memory` | Server ran out of memory | Yes |
| `sandbox_crash` | Sandbox environment crashed | Yes |

## ToolErrorCode

| Code | Description | Retryable |
|------|-------------|-----------|
| `UNKNOWN_TOOL` | Tool name not found in registry | No |
| `TOOL_DENIED` | Tool not allowed by policy | No |
| `TOOL_ERROR` | Tool execution failed | Yes |

## SkillErrorCode

| Code | Description | Retryable |
|------|-------------|-----------|
| `UNKNOWN_SKILL` | Skill name not found | No |
| `SKILL_ERROR` | Skill execution failed | Yes |
| `RUNTIME_ERROR` | Runtime error during skill | Yes |

## ChainErrorCode

| Code | Description | Retryable |
|------|-------------|-----------|
| `CHAIN_CYCLE` | DAG contains a cycle | No |
| `CHAIN_NODE_ERROR` | A node in the chain failed | Yes |

## MCPErrorCode

| Code | Description | Retryable |
|------|-------------|-----------|
| `server_not_found` | MCP server ID not registered | No |
| `unavailable` | MCP server is not connected | Yes |
| `tool_not_found` | Tool not found on any MCP server | No |
| `resource_not_found` | Resource URI not found | No |
| `prompt_not_found` | Prompt name not found | No |
| `transport_error` | MCP transport connection error | Yes |
| `protocol_error` | MCP protocol violation | No |
| `sampling_refused` | Agent refused LLM sampling request | No |
| `capability_missing` | MCP capability not available | No |

## Error Response Format

All errors are returned as `A2EError` messages:

```json
{
  "a2e": "1.0",
  "type": "error",
  "id": "<uuid>",
  "ts": 1716123456.789,
  "req_id": "<original-request-id>",
  "code": "tool_error",
  "message": "Tool 'write_file' failed: Permission denied",
  "detail": {
    "tool_name": "write_file",
    "path": "/root/secret.txt",
    "os_error": "EACCES"
  },
  "retryable": true,
  "capability_name": "tools"
}
```

## Client Error Handling

On the client side, `A2EError` responses are wrapped in `A2EClientError`:

```python
try:
    result = client.rpc(request, timeout=10)
except A2EClientError as e:
    print(f"Code: {e.code}")
    print(f"Message: {e.message}")
    print(f"Retryable: {e.retryable}")
    print(f"Detail: {e.detail}")
    print(f"Capability: {e.capability_name}")
    print(f"Events before error: {len(e.events)}")
```

## Retry Strategy

| Code Pattern | Strategy |
|-------------|---------|
| `retryable=True` | Exponential backoff retry (1s, 2s, 4s, ...) |
| `retryable=False` | Do not retry — fix the request |
| `timeout` | Increase timeout and retry |
| `unauthorized` | Fix auth_token, do not retry |
| `version_mismatch` | Update protocol version, do not retry |
