# Audit System

## Overview

A2E provides built-in structured audit logging for all message processing. Every plugin handler records an `AuditEntry` with timing, byte sizes, and success/error status. Audit is **best-effort** — failures are caught and never crash the handler.

## AuditEntry

| Field | Type | Description |
|-------|------|-------------|
| `ts` | `float` | Unix epoch timestamp |
| `session_id` | `str` | Session identifier |
| `req_id` | `str` | The request's correlation ID |
| `correlation_id` | `str` | Additional correlation (e.g. chain node) |
| `success` | `bool` | Whether the handler succeeded |
| `duration_ms` | `int` | Processing time in milliseconds |
| `error_code` | `str \| None` | Error code if failed |
| `input_bytes` | `int` | Size of the input message in bytes |
| `output_bytes` | `int` | Size of the output message in bytes |

## AuditLog

Thread-safe audit logger that writes entries to both a Python logger and an optional file.

```python
class AuditLog:
    def __init__(self, path: Path = None, logger: Logger = None):
        self._lock = threading.Lock()  # Thread-safe file writes

    def record(self, entry: AuditEntry):
        data = entry.model_dump_json()
        self.logger.info(data)
        if self.path:
            with self._lock:
                with open(self.path, "a") as f:
                    f.write(data + "\n")
```

### Rotating File Handler

When configured with `audit.path`, a `RotatingFileHandler` is attached:
- **Max file size**: 10 MB (`max_bytes`)
- **Backup count**: 5 rotated files (`backup_count`)
- Old files are renamed: `audit.jsonl.1`, `audit.jsonl.2`, etc.

## Factory Functions

### build_audit_log(config)

```python
from a2e.core.audit import build_audit_log

audit_log = build_audit_log(config)
# Returns AuditLog if audit.enabled, else None
```

Creates a dedicated `"a2e.audit"` logger with:
1. `StreamHandler` (console output)
2. `RotatingFileHandler` if `audit.path` is set

### build_session_id(config)

```python
from a2e.core.audit import build_session_id

session_id = build_session_id(config)
# If session_id_source == "host_id": returns config.host_id
# If session_id_source == "uuid": returns fresh UUID hex
```

## Plugin Integration

Every plugin's `audit_handle()` method is called after processing a message:

```python
# In A2EPlugin
def audit_handle(self, msg, response, req_id, t0):
    try:
        entry = AuditEntry(
            ts=time.time(),
            session_id=self.session_id,
            req_id=req_id,
            correlation_id="",
            success=not isinstance(response, A2EError),
            duration_ms=int((time.time() - t0) * 1000),
            error_code=response.code if isinstance(response, A2EError) else None,
            input_bytes=len(msg.model_dump_json()),
            output_bytes=len(response.model_dump_json()) if response else 0
        )
        self.audit_log.record(entry)
    except Exception:
        print(f"Audit recording failed")  # Never crashes the plugin
```

The `audit_log` is injected into each plugin during `setup()`:

```python
# In A2EServerRuntimeExecutor._load_plugins()
plugin.setup(self, {
    **plugin_config.model_dump(),
    "audit_log": self.audit_log,
    "session_id": self.session_id
})
```

## Configuration

```yaml
audit:
  enabled: true
  path: "/var/log/a2e/audit.jsonl"
  rotate:
    max_bytes: 10485760   # 10 MB
    backup_count: 5
  session_id_source: "uuid"  # or "host_id"
```
