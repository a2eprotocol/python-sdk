"""Client-side implementation of the ``planning`` capability (``planning/*``).

Mirrors the SDK's other capability clients (tools/memory/...): it takes an
``A2EClient``, registers the capability's wire types for response decoding, and
exposes typed methods.

The wire types live in :mod:`a2e.caps.planning.protocol` and are wire-compatible
with the Xceed host's planning plugin (same ``type`` strings + fields) — so the
agent uses this module instead of importing the host package (xa.env).
"""
from __future__ import annotations

from typing import Optional

from a2e.core.client import A2EClient
from a2e.caps.planning.protocol import (
    PLANNING_TYPE_MAP,
    PlanCreateRequest,
    PlanListRequest,
    TaskAddRequest,
    TaskUpdateRequest,
    TaskListRequest,
    PlanBoardRequest,
    PlanCreateResponse,
    PlanListResponse,
    TaskAddResponse,
    TaskUpdateResponse,
    TaskListResponse,
    PlanBoardResponse,
)


def _norm(msg_types: dict) -> dict:
    """Registry keys must be wire strings, not enum members."""
    return {getattr(k, "value", k): v for k, v in msg_types.items()}


class PlanningAPI:
    """Typed client for the ``planning`` namespace."""

    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(_norm(PLANNING_TYPE_MAP))

    def plan_create(self, name: str = "default", columns: Optional[list] = None,
                    description: str = "", timeout: int = 30) -> PlanCreateResponse:
        req = PlanCreateRequest(name=name, columns=columns or [],
                                description=description)
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, PlanCreateResponse):
            raise ConnectionError(f"Unexpected plan create response: {type(resp)}")
        return resp

    def plan_list(self, timeout: int = 30) -> PlanListResponse:
        resp = self._c.rpc(PlanListRequest(), timeout=timeout)
        if not isinstance(resp, PlanListResponse):
            raise ConnectionError(f"Unexpected plan list response: {type(resp)}")
        return resp

    def task_add(self, plan_id: str, title: str, status: str = "backlog",
                 description: str = "", assignee: str = "",
                 deps: Optional[list] = None, metadata: Optional[dict] = None,
                 timeout: int = 30) -> TaskAddResponse:
        req = TaskAddRequest(plan_id=plan_id, title=title, status=status,
                             description=description, assignee=assignee,
                             deps=deps or [], metadata=metadata or {})
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, TaskAddResponse):
            raise ConnectionError(f"Unexpected task add response: {type(resp)}")
        return resp

    def task_update(self, plan_id: str, task_id: str, status: str = "",
                    assignee: str = "", deps: Optional[list] = None,
                    timeout: int = 30) -> TaskUpdateResponse:
        req = TaskUpdateRequest(plan_id=plan_id, task_id=task_id, status=status,
                                assignee=assignee, deps=deps or [])
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, TaskUpdateResponse):
            raise ConnectionError(f"Unexpected task update response: {type(resp)}")
        return resp

    def task_list(self, plan_id: str = "", status: str = "",
                  timeout: int = 30) -> TaskListResponse:
        resp = self._c.rpc(TaskListRequest(plan_id=plan_id, status=status),
                            timeout=timeout)
        if not isinstance(resp, TaskListResponse):
            raise ConnectionError(f"Unexpected task list response: {type(resp)}")
        return resp

    def plan_board(self, plan_id: str = "",
                   timeout: int = 30) -> PlanBoardResponse:
        resp = self._c.rpc(PlanBoardRequest(plan_id=plan_id), timeout=timeout)
        if not isinstance(resp, PlanBoardResponse):
            raise ConnectionError(f"Unexpected plan board response: {type(resp)}")
        return resp


__all__ = ["PlanningAPI"]
