"""Client-side implementation of the ``multi_agent`` capability.

Mirrors the SDK's other capability clients (tools/memory/planning/...): takes an
``A2EClient``, registers the capability's wire types, and exposes typed methods.

The wire types live in :mod:`a2e.caps.multi_agent.protocol` and are
wire-compatible with the Xceed host's multi_agent plugin — so the agent uses
this module instead of importing the host package (xa.env).
"""
from __future__ import annotations

from typing import Optional

from a2e.core.client import A2EClient
from a2e.caps.multi_agent.protocol import (
    MULTI_AGENT_TYPE_MAP,
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
)


def _norm(msg_types: dict) -> dict:
    """Registry keys must be wire strings, not enum members."""
    return {getattr(k, "value", k): v for k, v in msg_types.items()}


class MultiAgentAPI:
    """Typed client for the ``multi_agent`` namespace (spawn/delegate/await)."""

    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(_norm(MULTI_AGENT_TYPE_MAP))

    def spawn(self, name: str, role: str = "", model: str = "default",
              max_steps: int = 20, metadata: Optional[dict] = None,
              timeout: int = 30) -> SpawnResp:
        req = SpawnReq(name=name, role=role, model=model, max_steps=max_steps,
                       metadata=metadata or {})
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, SpawnResp):
            raise ConnectionError(f"Unexpected spawn response: {type(resp)}")
        return resp

    def delegate(self, subagent_id: str, task_name: str, instruction: str,
                 success_criteria: Optional[list] = None,
                 timeout: int = 30) -> DelegateResp:
        req = DelegateReq(subagent_id=subagent_id, task_name=task_name,
                          instruction=instruction,
                          success_criteria=success_criteria or [])
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, DelegateResp):
            raise ConnectionError(f"Unexpected delegate response: {type(resp)}")
        return resp

    def await_(self, subagent_id: str, timeout: int = 30) -> AwaitResp:
        resp = self._c.rpc(AwaitReq(subagent_id=subagent_id), timeout=timeout)
        if not isinstance(resp, AwaitResp):
            raise ConnectionError(f"Unexpected await response: {type(resp)}")
        return resp

    def list(self, timeout: int = 30) -> ListResp:
        resp = self._c.rpc(ListReq(), timeout=timeout)
        if not isinstance(resp, ListResp):
            raise ConnectionError(f"Unexpected list response: {type(resp)}")
        return resp

    def terminate(self, subagent_id: str, timeout: int = 30) -> TerminateResp:
        resp = self._c.rpc(TerminateReq(subagent_id=subagent_id), timeout=timeout)
        if not isinstance(resp, TerminateResp):
            raise ConnectionError(f"Unexpected terminate response: {type(resp)}")
        return resp


__all__ = ["MultiAgentAPI"]
