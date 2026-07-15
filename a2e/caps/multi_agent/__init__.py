"""``multi_agent`` capability — shared wire types + client-side API.

The agent side consumes :class:`MultiAgentAPI` from this package (via
``a2e.caps.multi_agent.client``) instead of importing the host package.
"""
from a2e.caps.multi_agent.protocol import (
    MessageType,
    SubagentStatus,
    SpawnReq,
    DelegateReq,
    AwaitReq,
    ListReq,
    TerminateReq,
    SpawnResp,
    DelegateResp,
    AwaitResp,
    ListResp,
    TerminateResp,
    MULTI_AGENT_TYPE_MAP,
)
from a2e.caps.multi_agent.client import MultiAgentAPI

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
    "MultiAgentAPI",
]
