# ═════════════════════════════════════════════════════════════════════════════
# ── NAMESPACE: proc/*  ───────────────────────────────────────────────────────
#
# Long-running process management.  Unlike tool/call (which runs to completion),
# proc/* keeps a process alive so the agent can read/write its I/O incrementally.
# ═════════════════════════════════════════════════════════════════════════════
import pdb
from enum import Enum
from pydantic import BaseModel, Field
from a2e.caps.base.protocol import (
    A2EMessage,
    A2EEvent,
)


class ProcState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    CRASHED = "crashed"
    TIMEDOUT = "timedout"


class ProcStatus(BaseModel):
    proc_id: str
    cmd: str
    state: str   # ProcState value
    pid: int = 0
    exit_code: int | None = None
    started_at: float = 0.0


class ProcMCPError(str, Enum):
    # Process-specific
    UNKNOWN_PROC = "unknown_proc"
    PROC_DEAD = "proc_dead"
    PROC_LIMIT = "proc_limit"        # session process quota exceeded


class MessageType(str, Enum):
    PROC_SPAWN_REQ = "proc/spawn/req"
    PROC_SPAWN_RESP = "proc/spawn/resp"
    PROC_WRITE_REQ = "proc/write/req"
    PROC_WRITE_RESP = "proc/write/resp"
    PROC_READ_EVENT = "proc/read/event"
    PROC_KILL_REQ = "proc/kill/req"
    PROC_KILL_RESP = "proc/kill/resp"
    PROC_STATUS_REQ = "proc/status/req"
    PROC_STATUS_RESP = "proc/status/resp"


class ProcSpawnRequest(A2EMessage):
    """
    Agent → Host.  Spawn a persistent process.

    `cmd`         — command + args list
    `cwd`         — working directory (default: host CWD)
    `env`         — additional env vars to inject
    `stdin_mode`  — "pipe" | "null"
    `timeout`     — auto-kill after this many seconds (0 = no limit)
    """
    type: MessageType = MessageType.PROC_SPAWN_REQ
    session_id: str = ""
    cmd: list[str] = Field(default_factory=list)
    cwd: str = ""
    env: dict = Field(default_factory=dict)
    stdin_mode: str = "pipe"
    timeout: int = 0


class ProcSpawnResponse(A2EMessage):
    """Host → Agent.  Returns a proc_id for subsequent proc/* messages."""
    type: MessageType = MessageType.PROC_SPAWN_RESP
    req_id: str = ""
    proc_id: str = ""
    ok: bool = False
    pid: int = 0
    error: str = ""


class ProcWriteRequest(A2EMessage):
    """Agent → Host.  Write a chunk to the process's stdin."""
    type: MessageType = MessageType.PROC_WRITE_REQ
    proc_id: str = ""
    data: str = ""   # UTF-8 text; use base64 field for binary
    eof: bool = False


class ProcWriteResponse(A2EMessage):
    """Host _ Agent.  Returns a proc_id for subsequent proc/* messages."""
    type: MessageType = MessageType.PROC_WRITE_RESP
    req_id: str = ""
    proc_id: str = ""
    ok: bool = False
    pid: int = 0
    error: str = ""


class ProcReadEvent(A2EEvent):
    """
    Host → Agent (server-initiated).  A chunk of process stdout/stderr.
    Emitted as the process produces output; no req_id (push event).
    """
    type: MessageType = MessageType.PROC_READ_EVENT
    proc_id: str = ""
    stream_type: str = "stdout"   # "stdout" | "stderr"


class ProcKillRequest(A2EMessage):
    """Agent → Host.  Terminate a process."""
    type: MessageType = MessageType.PROC_KILL_REQ
    proc_id: str = ""
    signal: str = "SIGTERM"   # SIGTERM | SIGKILL | SIGINT


class ProcKillResponse(A2EMessage):
    type: MessageType = MessageType.PROC_KILL_RESP
    req_id: str = ""
    ok: bool = False
    state: str = ""   # final ProcState


class ProcStatusRequest(A2EMessage):
    """Agent → Host.  Query the status of one or all processes."""
    type: MessageType = MessageType.PROC_STATUS_REQ
    proc_id: str = ""   # empty = all procs in this session


class ProcStatusResponse(A2EMessage):
    type: MessageType = MessageType.PROC_STATUS_RESP
    req_id: str = ""
    proc_id: str
    status: str
    error: str


PROC_TYPE_MAP = {
    MessageType.PROC_SPAWN_REQ: ProcSpawnRequest,
    MessageType.PROC_SPAWN_RESP: ProcSpawnResponse,

    MessageType.PROC_WRITE_REQ: ProcWriteRequest,
    MessageType.PROC_WRITE_RESP: ProcWriteResponse,

    MessageType.PROC_READ_EVENT: ProcReadEvent,

    MessageType.PROC_KILL_REQ: ProcKillRequest,
    MessageType.PROC_KILL_RESP: ProcKillResponse,

    MessageType.PROC_STATUS_REQ: ProcStatusRequest,
    MessageType.PROC_STATUS_RESP: ProcStatusResponse,
}
