import uuid
import time
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any


A2E_VERSION = "1.0"


class MessageType(str, Enum):
    # Handshake
    HANDSHAKE_REQ = "handshake/req"
    HANDSHAKE_RESP = "handshake/resp"

    INVOKE_EVT = "invoke/event"

    # Lifecycle
    PING = "ping"
    PONG = "pong"
    SHUTDOWN = "shutdown"

    # Errors (always paired with the request they answer)
    ERROR = "error"


class EventKind(str, Enum):
    PROGRESS = "progress"   # { "pct": 0-100, "message": "..." }
    ARTIFACT = "artifact"   # partial / incremental file or data chunk
    LOG = "log"        # skill debug line (shown only at disclosure >= DEBUG)
    STATUS = "status"     # one-liner status update for the agent UI


# ═════════════════════════════════════════════════════════════════════════════
# A2E message base
# ═════════════════════════════════════════════════════════════════════════════
class A2EMessage(BaseModel):
    """
    Base for all A2E-native messages.
    Carries both a2e and scp version stamps for mixed-protocol routers.
    """
    type: str
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    version: str = A2E_VERSION
    ts: float = Field(default_factory=time.time)

    def to_dict(self) -> dict:
        return self.model_dump()

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex


# ═════════════════════════════════════════════════════════════════════════════
# Handshake
# ═════════════════════════════════════════════════════════════════════════════
class HandshakeRequest(A2EMessage):
    """
    Agent → Host.  Sent once per session before the first invoke.

    `agent_caps` lists what the agent supports (e.g. "streaming", "artifacts").
    `auth_token` is an HMAC the host uses to verify the agent's identity;
    blank = unauthenticated (development mode only).
    """
    type: MessageType = MessageType.HANDSHAKE_REQ
    agent_id: str = ""
    agent_caps: list[str] = Field(default_factory=list)
    auth_token: str = ""


# ═════════════════════════════════════════════════════════════════════════════
# Extended handshake (A2E capabilities negotiation)
# ═════════════════════════════════════════════════════════════════════════════
class A2ECapability(str, Enum):
    """
    Capabilities the agent and host negotiate during handshake.
    These extend the SCP "streaming" / "artifacts" set.
    """
    SKILL = "skill"      # SCP compat
    TOOLS = "tools"               # native tool execution
    TOOLKITS = "toolkits"          # native toolkits
    ENV = "env"              # env/observe messages
    PROC = "proc"          # proc/* management
    MEMORY = "memory"         # memory/* store
    LEARNING = "learning"       # learn/* subsystem
    CHAINS = "chains"         # chain/* pipelines
    MULTI_AGENT = "multi_agent"    # peer agent coordination (future)
    PLANNING = "planning"      # generic planning / task-tracking (kanban = a view)
    MCP = "mcp"            # mcp/* bridge namespace
    TEST = "test"           # generic test capability


class Capability(BaseModel):
    """
    Final negotiated capability between host and agent.
    """
    capability: A2ECapability
    enabled: bool = True

    # Arbitrary capability-specific metadata
    metadata: dict[str, Any] = Field(default_factory=dict)


class HandshakeResponse(A2EMessage):
    """
    Host → Agent.  Confirms supported features and per-session limits.

    `session_id` must accompany every subsequent invoke.
    `accepted_caps` is the intersection of agent_caps and host support.
    """
    type: MessageType = MessageType.HANDSHAKE_RESP
    req_id: str = ""
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    accepted_caps: list[Capability] = Field(default_factory=list)
    max_parallel: int = 4     # max concurrent invokes this session
    ok: bool = True
    reason: str = ""    # populated when ok=False


class A2EErrorCode(str, Enum):
    # Inherited from SCP
    PARSE_ERROR = "parse_error"
    RUNTIME_ERROR = "runtime_error"
    INVALID_MESSAGE = "invalid_message"
    VERSION_MISMATCH = "version_mismatch"
    UNAUTHORIZED = "unauthorized"
    SCHEMA_VIOLATION = "schema_violation"
    TIMEOUT = "timeout"
    OOM = "out_of_memory"
    SANDBOX_CRASH = "sandbox_crash"


# ═════════════════════════════════════════════════════════════════════════════
# Errors
# ═════════════════════════════════════════════════════════════════════════════
class A2EError(A2EMessage):
    """
    Host → Agent (or Agent → Host for protocol violations).

    `retryable`  hints whether the agent should retry without changes.
    `req_id`     echoes the id of the message that caused this error.
    """
    type: MessageType = MessageType.ERROR
    req_id: str = ""
    code: str
    message: str = ""
    detail: dict = Field(default_factory=dict)
    retryable: bool = False
    capability_name: str = ""


# ═════════════════════════════════════════════════════════════════════════════
# Lifecycle
# ═════════════════════════════════════════════════════════════════════════════
class Ping(A2EMessage):
    type: MessageType = MessageType.PING


class Pong(A2EMessage):
    type: MessageType = MessageType.PONG
    req_id: str = ""
    uptime_seconds: float = 0.0


class Shutdown(A2EMessage):
    """Agent → Host.  Graceful teardown; host drains in-flight tasks first."""
    type: MessageType = MessageType.SHUTDOWN
    timeout: int = 10   # seconds to wait for in-flight tasks


class A2EEvent(A2EMessage):
    """
    Host → Agent.  Zero or more streaming events before the final response.

    kind = EventKind value
    data = event payload (shape depends on kind):
      progress  → { pct: int, message: str }
      artifact  → { name: str, mime: str, chunk: str (base64), final: bool }
      log       → { level: str, message: str }
      status    → { message: str }
    """
    type: MessageType = MessageType.INVOKE_EVT
    kind: str = EventKind.STATUS.value
    req_id: str = ""
    data: dict = Field(default_factory=dict)
    seq: int = 0    # monotonic sequence number within this invocation


A2E_BASE_TYPE_MAP: dict[str, type] = {
    MessageType.HANDSHAKE_REQ.value: HandshakeRequest,
    MessageType.HANDSHAKE_RESP.value: HandshakeResponse,
    MessageType.PING.value: Ping,
    MessageType.PONG.value: Pong,
    MessageType.SHUTDOWN.value: Shutdown,
    MessageType.ERROR.value: A2EError,
    MessageType.INVOKE_EVT.value: A2EEvent,
}
