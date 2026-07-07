"""
Planning capability protocol models for A2E (``planning/*`` namespace).

A generic planning primitive: plans → tasks with ``status`` + configurable
column vocabulary. A *kanban board* is just one concrete View of a plan
(tasks grouped by their ``status`` column). Other planning schemes (waterfall,
OKR, sprints) reuse the same task/status model with different vocabularies.

Messages:
  - ``planning/plan/create``   → create a plan (optional column vocabulary)
  - ``planning/plan/list``     → list plans
  - ``planning/task/add``      → add a task to a plan (status, deps, assignee)
  - ``planning/task/update``   → change status / assignee / deps
  - ``planning/task/list``     → list tasks (filter by plan / status)
  - ``planning/plan/board``    → kanban view: tasks grouped by status column
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List

from a2e.caps.base.protocol import A2EMessage


# Default column vocabulary = classic kanban. Plans may override.
DEFAULT_COLUMNS = ["backlog", "todo", "in_progress", "done"]


# ── Message types ──────────────────────────────────────────────────────────

class PlanningMessageType(str, Enum):
    PLAN_CREATE = "planning/plan/create"
    PLAN_LIST = "planning/plan/list"
    TASK_ADD = "planning/task/add"
    TASK_UPDATE = "planning/task/update"
    TASK_LIST = "planning/task/list"
    PLAN_BOARD = "planning/plan/board"  # kanban-style grouped view


# ── Requests ───────────────────────────────────────────────────────────────

class PlanCreateRequest(A2EMessage):
    type: str = PlanningMessageType.PLAN_CREATE
    name: str = "default"
    columns: List[str] = []        # empty → default kanban columns
    description: str = ""


class PlanListRequest(A2EMessage):
    type: str = PlanningMessageType.PLAN_LIST


class TaskAddRequest(A2EMessage):
    type: str = PlanningMessageType.TASK_ADD
    plan_id: str
    title: str
    status: str = "backlog"
    description: str = ""
    assignee: str = ""
    deps: List[str] = []             # task_ids this depends on
    metadata: Dict[str, Any] = {}


class TaskUpdateRequest(A2EMessage):
    type: str = PlanningMessageType.TASK_UPDATE
    plan_id: str
    task_id: str
    status: str = ""
    assignee: str = ""
    deps: List[str] = []


class TaskListRequest(A2EMessage):
    type: str = PlanningMessageType.TASK_LIST
    plan_id: str = ""
    status: str = ""


class PlanBoardRequest(A2EMessage):
    type: str = PlanningMessageType.PLAN_BOARD
    plan_id: str = ""               # empty → all plans, one board each


# ── Responses ──────────────────────────────────────────────────────────────

class PlanCreateResponse(A2EMessage):
    type: str = PlanningMessageType.PLAN_CREATE + "/resp"
    req_id: str = ""
    success: bool = False
    plan_id: str = ""
    columns: List[str] = []


class PlanListResponse(A2EMessage):
    type: str = PlanningMessageType.PLAN_LIST + "/resp"
    req_id: str = ""
    plans: List[dict] = []


class TaskAddResponse(A2EMessage):
    type: str = PlanningMessageType.TASK_ADD + "/resp"
    req_id: str = ""
    success: bool = False
    task_id: str = ""
    status: str = ""


class TaskUpdateResponse(A2EMessage):
    type: str = PlanningMessageType.TASK_UPDATE + "/resp"
    req_id: str = ""
    success: bool = False
    task_id: str = ""


class TaskListResponse(A2EMessage):
    type: str = PlanningMessageType.TASK_LIST + "/resp"
    req_id: str = ""
    tasks: List[dict] = []


class PlanBoardResponse(A2EMessage):
    type: str = PlanningMessageType.PLAN_BOARD + "/resp"
    req_id: str = ""
    boards: List[dict] = []


# ── TYPE_MAP (register on the client for response decoding) ──────────────

PLANNING_TYPE_MAP: dict[str, type] = {
    PlanningMessageType.PLAN_CREATE: PlanCreateRequest,
    PlanningMessageType.PLAN_LIST: PlanListRequest,
    PlanningMessageType.TASK_ADD: TaskAddRequest,
    PlanningMessageType.TASK_UPDATE: TaskUpdateRequest,
    PlanningMessageType.TASK_LIST: TaskListRequest,
    PlanningMessageType.PLAN_BOARD: PlanBoardRequest,
    PlanningMessageType.PLAN_CREATE + "/resp": PlanCreateResponse,
    PlanningMessageType.PLAN_LIST + "/resp": PlanListResponse,
    PlanningMessageType.TASK_ADD + "/resp": TaskAddResponse,
    PlanningMessageType.TASK_UPDATE + "/resp": TaskUpdateResponse,
    PlanningMessageType.TASK_LIST + "/resp": TaskListResponse,
    PlanningMessageType.PLAN_BOARD + "/resp": PlanBoardResponse,
}
