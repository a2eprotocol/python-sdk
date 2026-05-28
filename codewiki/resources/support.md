# Support

Resources for getting help, troubleshooting issues, and contributing to A2E.

---

## Documentation Map

Before reaching out for help, the answer may already be in the docs:

| What you need | Where to look |
|---------------|--------------|
| Get started quickly | [Quick Start](/getting-started/quickstart) |
| Install A2E | [Installation](/getting-started/installation) |
| Understand the architecture | [Architecture Overview](/architecture/overview) |
| Look up an API method | [Client API](/sdk-reference/client-api) or [Server API](/sdk-reference/server-api) |
| Configure the host | [Configuration](/sdk-reference/configuration) |
| Understand the wire format | [Message Format](/protocol-spec/message-format) |
| Debug a connection issue | [Handshake](/protocol-spec/handshake) and [Error Codes](/protocol-spec/error-codes) |
| Learn a specific capability | [Capabilities Index](/capabilities/tools) |
| Write a custom plugin | [Writing a Plugin](/cookbook/writing-a-plugin) |
| Integrate with MCP | [MCP Integration](/cookbook/mcp-integration) and [MCP Bridge](/cookbook/mcp-bridge) |
| Build a memory plugin | [Memory (Plugin & Client)](/cookbook/memory-plugin) |
| Build custom tools | [Custom Tools (Plugin & Client)](/cookbook/custom-tools) |
| Build a toolkit | [Toolkit Builder (Plugin & Client)](/cookbook/toolkit-builder) |
| Check a term | [Glossary](/resources/glossary) |
| Common questions | [FAQ](/resources/faq) |
| Security concerns | [Security & Trust](/resources/security-trust) |

---

## Troubleshooting Guide

### Connection Issues

#### "Connection refused" when connecting to the server

**Symptoms**: `A2EClient` cannot establish a connection; `ConnectionRefusedError`.

**Checks**:
1. Is the server running? Check `ps aux | grep uvicorn` or your process manager
2. Is the server bound to the correct host/port? Check `config.yaml` → `server.host` and `server.port`
3. If binding to `0.0.0.0`, can you reach the host's IP from the client?
4. Is a firewall blocking the port? Check `iptables -L -n` or cloud security groups

#### Handshake fails with `auth_failed`

**Symptoms**: `handshake/resp` returns `ok=false` with `reason="auth_failed"`.

**Checks**:
1. Verify `auth_token` in `A2EClient` matches `server.auth_token` in `config.yaml`
2. Check for whitespace or encoding issues in the token string
3. Ensure the token is passed as a string, not accidentally as None or empty

#### Handshake fails with `version_mismatch`

**Symptoms**: `handshake/resp` returns `ok=false` with `reason="version_mismatch"`.

**Checks**:
1. Client and server must use the same protocol version (currently `"1.0"`)
2. Ensure you're running the same `a2e` package version on both sides
3. Check `pip show a2e` for the installed version

#### SSE stream disconnects

**Symptoms**: Client stops receiving events; `event_callback` stops firing.

**Checks**:
1. Check server logs for errors or OOM kills
2. Verify the SSE connection is still active (some proxies timeout idle connections)
3. Increase proxy timeout settings (e.g., `proxy_read_timeout` in nginx)
4. Use the client's reconnection logic (if implemented in your transport config)

### Plugin Issues

#### Plugin not found at startup

**Symptoms**: `ModuleNotFoundError` or `ImportError` during server startup.

**Checks**:
1. Is the plugin module installed? `pip list | grep your-plugin-package`
2. Is the `cls` path correct in `config.yaml`? Format: `module.path.ClassName`
3. Is the module on `PYTHONPATH`? If running from a custom directory, set it explicitly
4. Can you import it manually? `python -c "from mypackage import MyPlugin"`

#### Plugin throws `schema_violation`

**Symptoms**: Handler receives `A2EError` with code `schema_violation`.

**Checks**:
1. The incoming message doesn't match the expected Pydantic model
2. Check required fields in the protocol spec for that message type
3. Enable debug logging to see the raw message and validation error
4. Verify the client is sending the correct protocol version

#### Plugin doesn't receive messages

**Symptoms**: Plugin's `handle()` is never called despite messages being sent.

**Checks**:
1. Is the capability negotiated? Check `accepted_caps` in the handshake response
2. Is `supported_messages()` returning the correct type map?
3. Is the plugin `enabled: true` in `metadata`?
4. Is another `exclusive` plugin handling the same message type?

### Memory Issues

#### Memory recall returns nothing

**Symptoms**: `memory.recall()` returns empty or `None` after storing a value.

**Checks**:
1. Are you querying the same tier you stored to? Working memory is session-scoped
2. Did the entry have a `ttl` that expired?
3. Is the memory plugin enabled and the capability negotiated?
4. Check the memory limits — entries may be evicted if the tier is full

### Tool Issues

#### "Unknown tool" error

**Symptoms**: `tool/call/resp` returns `UNKNOWN_TOOL`.

**Checks**:
1. Is the tool registered in the plugin? Call `tool/list` to see available tools
2. Check for typos in the tool name (case-sensitive)
3. If using a toolkit, is the toolkit configured and in `running` state?
4. If using MCP, is the MCP server connected?

#### Tool execution timeout

**Symptoms**: `tool/call/resp` returns `timeout` error.

**Checks**:
1. Increase the `timeout` parameter in `client.rpc()` (default may be too low)
2. Is the tool doing I/O that's slow (network calls, large file reads)?
3. Check server load — high concurrency can slow things down
4. Consider making the tool async or breaking it into smaller steps

---

## Getting Help

### GitHub Issues

For bug reports, feature requests, and documentation issues:

1. **Search existing issues** first — your problem may already be reported or solved
2. **Use the issue templates** — they help you provide the right information
3. **Include**:
   - A2E version (`pip show a2e`)
   - Python version (`python --version`)
   - Minimal reproduction steps
   - Expected vs. actual behavior
   - Relevant logs or error messages

### Discussions

For questions that aren't bugs or feature requests:

- **"How do I..."** questions
- Architecture and design discussions
- Plugin development guidance
- Integration patterns with other tools

### Community Channels

| Channel | Best For |
|---------|----------|
| GitHub Issues | Bug reports, feature requests |
| GitHub Discussions | Q&A, design discussions |
| Discord / Chat | Quick questions, real-time help |

Check the project repository for links to active community channels.

---

## Debugging Techniques

### Enable Verbose Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or specifically for A2E
logging.getLogger("a2e").setLevel(logging.DEBUG)
```

### Inspect the Wire Protocol

For HTTP mode, log the raw NDJSON traffic:

```python
# On the client side, set an out_handler on the transport
def debug_out(msg):
    print(f">>> {msg.model_dump_json()}")

def debug_in(msg):
    print(f"<<< {msg.model_dump_json()}")

client.transport.set_out_handler(debug_out)
# Messages from server are delivered through the handler
```

### Check Audit Logs

If audit is enabled, inspect the JSONL file:

```bash
# Recent errors
cat /var/log/a2e/audit.jsonl | python -c "
import sys, json
for line in sys.stdin:
    entry = json.loads(line)
    if not entry.get('success'):
        print(json.dumps(entry, indent=2))
"

# Slow operations (>1 second)
cat /var/log/a2e/audit.jsonl | python -c "
import sys, json
for line in sys.stdin:
    entry = json.loads(line)
    if entry.get('duration_ms', 0) > 1000:
        print(f'{entry[\"duration_ms\"]}ms - {entry[\"req_id\"]}')
"
```

### Test with DirectTransport

Eliminate network issues by testing with in-process transport:

```python
from a2e.core.transports.direct import DirectTransport

# Create cross-wired transport pair
client_transport = DirectTransport()
server_transport = DirectTransport()
client_transport.wire(server_transport)

# Use client_transport for A2EClient
# Wire server_transport into the server's executor
```

### Validate Messages Manually

```python
from a2e.caps.tools.protocol import ToolCallRequest

# Validate a message structure
try:
    msg = ToolCallRequest(
        type="tool/call/req",
        id="test-1",
        a2e="1.0",
        ts=1716123456.789,
        tool_name="read_file",
        arguments={"path": "/etc/hostname"}
    )
    print("Valid:", msg.model_dump_json())
except Exception as e:
    print("Invalid:", e)
```

---

## Contributing

### Reporting Bugs

1. Check if the bug exists in the latest version
2. Search existing issues for duplicates
3. Open an issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected behavior
   - Actual behavior (with error output)
   - Environment details (OS, Python version, A2E version)

### Suggesting Features

1. Describe the use case, not just the solution
2. Explain how it fits into the A2E architecture
3. Consider whether it should be a core feature or a plugin
4. Check if it can already be achieved with existing capabilities

### Contributing Code

1. Fork the repository
2. Create a feature branch
3. Write tests for your changes
4. Ensure all existing tests pass
5. Follow the existing code style (Pydantic v2 models, type hints throughout)
6. Submit a pull request with a clear description

### Writing Documentation

The documentation you're reading lives alongside the code. To improve it:

1. Documentation files are in the `codewiki/` directory
2. Follow the existing page structure and formatting
3. Include code examples that actually work
4. Cross-reference related pages with markdown links
5. Test code snippets before submitting

---

## Version Compatibility

| A2E Version | Protocol | Python | Pydantic | FastAPI |
|-------------|----------|--------|----------|---------|
| 0.1.x | 1.0 | 3.10+ | v2 | 0.100+ |

### Upgrading

- Check the changelog for breaking changes
- Protocol version mismatches are caught at handshake — update both client and server together
- Plugin APIs may change between minor versions — check the release notes

---

## FAQ Quick Links

For common questions, see [FAQ](/resources/faq):

- [What is A2E?](/resources/faq#what-is-a2e)
- [How do I handle errors?](/resources/faq#how-should-i-handle-errors)
- [Can I have multiple plugins for the same capability?](/resources/faq#can-i-have-multiple-plugins-for-the-same-capability)
- [What's the difference between tools and toolkits?](/resources/faq#whats-the-difference-between-tools-and-toolkits)
- [How do sessions work?](/resources/faq#how-do-sessions-work)

For security concerns, see [Security & Trust](/resources/security-trust).
