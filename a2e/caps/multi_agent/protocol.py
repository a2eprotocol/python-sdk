"""Wire types for the ``multi_agent`` capability (``multi_agent/*`` namespace).

This capability previously lived only inside the host package (xa.env.plugins
.multi_agent). It is moved into the a2e SDK so the *agent* side can build and
decode these messages without importing the host, and so the two sides share a
single source of truth for the wire contract.

Mirrors xa-agent-env/xa/env/plugins/multi_agent.py exactly (same ``type``
strings + fields).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from a2e.caps.base.protocol import A2EMessage, A2EError, A2EErrorCode


class MessageType(str, Enum):
    SPAWN = "multi_agent/spawn"
    DELEGATE = "multi_agent/delegate"
    AWAIT = "multi_agent/await"
    LIST = "multi_agent/list"
    TERMINATE = "multi_agent/terminate"


class SubagentStatus(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"


class SpawnReq(A2EMessage):
    type: str = MessageType.SPAWN
    name: str
    role: str = ""
    model: str = "default"
    max_steps: int = 20
    metadata: Dict[str, Any] = {}


class DelegateReq(A2EMessage):
    type: str = MessageType.DELEGATE
    subagent_id: str
    task_name: str
    instruction: str
    success_criteria: List[str] = []


class AwaitReq(A2EMessage):
    type: str = MessageType.AWAIT
    subagent_id: str


class ListReq(A2EMessage):
    type: str = MessageType.LIST


class TerminateReq(A2EMessage):
    type: str = MessageType.TERMINATE
    subagent_id: str


# ── Responses (must be registered on the client for decoding) ─────────
class SpawnResp(A2EMessage):
    type: str = MessageType.SPAWN + "/resp"
    req_id: str = ""
    subagent_id: str = ""
    status: str = ""


class DelegateResp(A2EMessage):
    type: str = MessageType.DELEGATE + "/resp"
    req_id: str = ""
    accepted: bool = True
    status: str = ""


class AwaitResp(A2EMessage):
    type: str = MessageType.AWAIT + "/resp"
    req_id: str = ""
    subagent_id: str = ""
    status: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None


class ListResp(A2EMessage):
    type: str = MessageType.LIST + "/resp"
    req_id: str = ""
    subagents: List[dict] = []


class TerminateResp(A2EMessage):
    type: str = MessageType.TERMINATE + "/resp"
    req_id: str = ""
    success: bool = False
    subagent_id: str = ""


MULTI_AGENT_TYPE_MAP = {
    MessageType.SPAWN: SpawnReq,
    MessageType.DELEGATE: DelegateReq,
    MessageType.AWAIT: AwaitReq,
    MessageType.LIST: ListReq,
    MessageType.TERMINATE: TerminateReq,
    MessageType.SPAWN + "/resp": SpawnResp,
    MessageType.DELEGATE + "/resp": DelegateResp,
    MessageType.AWAIT + "/resp": AwaitResp,
    MessageType.LIST + "/resp": ListResp,
    MessageType.TERMINATE + "/resp": TerminateResp,
}


__all__ = [
    "MessageType",
    "SubagentStatus",
    "SpawnReq",
    "DelegateReq",
    "AwaitReq",
    "ListReq",
    "TerminateReq",
    "SpawnResp",
    "DelegateResp",
    "AwaitResp",
    "ListResp",
    "TerminateResp",
    "MULTI_AGENT_TYPE_MAP",
    "A2EMessage",
    "A2EError",
    "A2EErrorCode",
]
