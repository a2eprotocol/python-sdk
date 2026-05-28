# Processes

```text
a2e/caps/proc/protocol.py — MessageType, ProcSpawn*, ProcState
a2e/caps/proc/plugin.py   — ProcPlugin (concrete)
a2e/caps/proc/client.py   — ProcsAPI
```

## Overview

The **proc** capability manages long-running subprocess lifecycle — spawn, write to stdin, read stdout/stderr, kill, and query status. Unlike tools (synchronous), processes are asynchronous and stream output over time.

## Protocol Messages (8 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `proc/spawn/req` | `ProcSpawnRequest` | Agent → Host |
| `proc/spawn/resp` | `ProcSpawnResponse` | Host → Agent |
| `proc/write/req` | `ProcWriteRequest` | Agent → Host |
| `proc/write/resp` | `ProcWriteResponse` | Host → Agent |
| `proc/read/event` | `ProcReadEvent` | Host → Agent (streaming) |
| `proc/kill/req` | `ProcKillRequest` | Agent → Host |
| `proc/kill/resp` | `ProcKillResponse` | Host → Agent |
| `proc/status/req` | `ProcStatusRequest` | Agent → Host |
| `proc/status/resp` | `ProcStatusResponse` | Host → Agent |

### Key Models

**ProcSpawnRequest**:
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Session identifier |
| `cmd` | `list[str]` | Command + args (e.g. `["python3", "script.py"]`) |
| `cwd` | `str` | Working directory |
| `env` | `dict` | Environment variables |
| `stdin_mode` | `str` | Stdin behavior |
| `timeout` | `float` | Process timeout |

**ProcState** enum: `RUNNING`, `STOPPED`, `CRASHED`, `TIMEDOUT`

**ProcReadEvent** (extends A2EEvent): Streaming output with `proc_id` and `stream_type` (`stdout` / `stderr`).

**ProcKillRequest**: `signal` field supports `SIGTERM`, `SIGKILL`, `SIGINT`.

## ProcPlugin (Concrete)

Unlike most plugins, `ProcPlugin` is a **concrete implementation** (not abstract). It uses `subprocess.Popen` internally:

```python
class ProcPlugin(A2EPlugin):
    name = "proc"
    priority = 5

    # Security: command allowlist
    allowed_commands = ["python3", "bash", "ls"]  # Configurable

    def _spawn(self, msg):
        # 1. Validate cmd against allowed_commands
        # 2. Spawn subprocess.Popen
        # 3. Start 3 daemon threads:
        #    - stdout reader -> emits ProcReadEvent
        #    - stderr reader -> emits ProcReadEvent
        #    - process waiter -> updates status on exit

    def _write(self, msg):
        # Write to process stdin, flush

    def _kill(self, msg):
        # Terminate process, mark status

    def _status(self, msg):
        # Return ProcStatus
```

**Runtime wrapper** — `ProcSession` tracks each process:
| Field | Type | Description |
|-------|------|-------------|
| `proc_id` | `str` | Process UUID |
| `process` | `Popen` | The subprocess |
| `req_id` | `str` | Spawn request ID |
| `status` | `ProcState` | Current state |
| `error` | `str` | Error if any |

### Configuration

```yaml
# In plugin metadata
allowed_commands:
  - python3
  - bash
  - ls
  - echo
timeout: 30
max_output_bytes: 1048576   # 1 MB
max_procs: 10
network_disabled: true
```

## ProcsAPI (Client)

```python
from a2e.caps.proc.client import ProcsAPI

procs = ProcsAPI(client)

# Spawn a process
resp = procs.spawn(
    cmd=["python3", "-c", "print('hello'); import time; time.sleep(5)"],
    on_output=lambda event: print(f"[{event.stream_type}] {event.data}")
)

proc_id = resp.proc_id

# Write to stdin
procs.write(proc_id, data="input data\n")

# Kill
procs.kill(proc_id, signal="SIGTERM")

# Check status
status = procs.status(proc_id)
print(f"State: {status.state}, Exit: {status.exit_code}")
```

::: warning
The `write()` method uses `_c._send()` (fire-and-forget), not RPC. There is no response guarantee.
:::
