"""
``HermesPlanningPlugin`` — a GENERIC planning capability for A2E.

This is the umbrella planning primitive (``type: planning`` in host config,
``planning`` in ``A2ECapability`` enum). A *kanban board* is just one concrete
view of a plan: tasks grouped by their ``status``, where status values are
drawn from a configurable column vocabulary. Other planning schemes (waterfall,
OKR, sprints) reuse the same task/status model with different vocabularies.

Storage: SQLite. Generic enough to back P3 (env RL loop) task tracking too.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List

from a2e.caps.base.protocol import A2EMessage, A2EError, A2EErrorCode
from a2e.caps.planning.protocol import (
    DEFAULT_COLUMNS,
    PLANNING_TYPE_MAP,
    PlanBoardRequest,
    PlanBoardResponse,
    PlanCreateRequest,
    PlanCreateResponse,
    PlanListRequest,
    PlanListResponse,
    PlanningMessageType,
    TaskAddRequest,
    TaskAddResponse,
    TaskListRequest,
    TaskListResponse,
    TaskUpdateRequest,
    TaskUpdateResponse,
)
from a2e.core.plugins import A2EPlugin


class HermesPlanningPlugin(A2EPlugin):
    name = "planning"
    priority = 0

    def __init__(self, host_instance, config: Any):
        super().setup(host_instance, config)
        self._root = config.get("ROOT", "/tmp/a2e/hermes-harness/planning")
        os.makedirs(self._root, exist_ok=True)
        self._db = os.path.join(self._root, "planning.db")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db, check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS plans (
                plan_id TEXT PRIMARY KEY, name TEXT, columns TEXT,
                description TEXT, created_at REAL)"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, plan_id TEXT, title TEXT, status TEXT,
                description TEXT, assignee TEXT, deps TEXT, metadata TEXT,
                created_at REAL)"""
        )
        self._conn.commit()

    def supported_messages(self) -> Dict[str, Any]:
        return {
            PlanningMessageType.PLAN_CREATE: PlanCreateRequest,
            PlanningMessageType.PLAN_LIST: PlanListRequest,
            PlanningMessageType.TASK_ADD: TaskAddRequest,
            PlanningMessageType.TASK_UPDATE: TaskUpdateRequest,
            PlanningMessageType.TASK_LIST: TaskListRequest,
            PlanningMessageType.PLAN_BOARD: PlanBoardRequest,
        }

    def handle(self, msg: A2EMessage):
        t = getattr(msg, "type", None)
        handler = {
            PlanningMessageType.PLAN_CREATE: self._create_plan,
            PlanningMessageType.PLAN_LIST: self._list_plans,
            PlanningMessageType.TASK_ADD: self._add_task,
            PlanningMessageType.TASK_UPDATE: self._update_task,
            PlanningMessageType.TASK_LIST: self._list_tasks,
            PlanningMessageType.PLAN_BOARD: self._board,
        }.get(t)
        if handler is None:
            return A2EError(
                req_id=msg.id,
                code=A2EErrorCode.INVALID_MESSAGE,
                message=f"unsupported planning message: {t}",
                retryable=False,
            )
        return handler(msg)

    # ── plan handlers ─────────────────────────────────────────────────

    def _create_plan(self, msg):
        plan_id = uuid.uuid4().hex[:12]
        cols = msg.columns or DEFAULT_COLUMNS
        with self._lock:
            self._conn.execute(
                "INSERT INTO plans VALUES (?,?,?,?,?)",
                (plan_id, msg.name, ",".join(cols), msg.description, time.time()),
            )
            self._conn.commit()
        return PlanCreateResponse(
            req_id=msg.id, success=True, plan_id=plan_id, columns=list(cols)
        )

    def _list_plans(self, msg):
        with self._lock:
            rows = self._conn.execute(
                "SELECT plan_id, name, columns FROM plans"
            ).fetchall()
        plans = [
            {"plan_id": r[0], "name": r[1], "columns": r[2].split(",")}
            for r in rows
        ]
        return PlanListResponse(req_id=msg.id, plans=plans)

    # ── task handlers ─────────────────────────────────────────────────

    def _add_task(self, msg):
        task_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    msg.plan_id,
                    msg.title,
                    msg.status,
                    msg.description,
                    msg.assignee,
                    json.dumps(msg.deps),
                    json.dumps(msg.metadata),
                    time.time(),
                ),
            )
            self._conn.commit()
        return TaskAddResponse(
            req_id=msg.id, success=True, task_id=task_id, status=msg.status
        )

    def _update_task(self, msg):
        sets, params = [], []
        if msg.status:
            sets.append("status=?")
            params.append(msg.status)
        if msg.assignee:
            sets.append("assignee=?")
            params.append(msg.assignee)
        if msg.deps:
            sets.append("deps=?")
            params.append(json.dumps(msg.deps))
        params += [msg.task_id, msg.plan_id]
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET " + ", ".join(sets)
                + " WHERE task_id=? AND plan_id=?",
                params,
            )
            self._conn.commit()
            ok = cur.rowcount > 0
        return TaskUpdateResponse(req_id=msg.id, success=ok, task_id=msg.task_id)

    def _list_tasks(self, msg):
        with self._lock:
            if msg.plan_id and msg.status:
                rows = self._conn.execute(
                    "SELECT task_id,title,status,assignee,plan_id FROM tasks "
                    "WHERE plan_id=? AND status=?",
                    (msg.plan_id, msg.status),
                ).fetchall()
            elif msg.plan_id:
                rows = self._conn.execute(
                    "SELECT task_id,title,status,assignee,plan_id FROM tasks "
                    "WHERE plan_id=?",
                    (msg.plan_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT task_id,title,status,assignee,plan_id FROM tasks"
                ).fetchall()
        tasks = [
            {"task_id": r[0], "title": r[1], "status": r[2],
             "assignee": r[3], "plan_id": r[4]}
            for r in rows
        ]
        return TaskListResponse(req_id=msg.id, tasks=tasks)

    # ── kanban (board) view ───────────────────────────────────────────

    def _board(self, msg):
        """Kanban = tasks grouped by status column. One board per plan."""
        with self._lock:
            if msg.plan_id:
                plans = self._conn.execute(
                    "SELECT plan_id, name, columns FROM plans WHERE plan_id=?",
                    (msg.plan_id,),
                ).fetchall()
            else:
                plans = self._conn.execute(
                    "SELECT plan_id, name, columns FROM plans"
                ).fetchall()
            tasks = self._conn.execute(
                "SELECT task_id,title,status,assignee,plan_id FROM tasks"
            ).fetchall()
        task_by_plan: Dict[str, List[dict]] = {}
        for tid, title, status, assignee, pid in tasks:
            task_by_plan.setdefault(pid, []).append(
                {"task_id": tid, "title": title, "status": status, "assignee": assignee}
            )
        boards = []
        for pid, name, cols in plans:
            columns = cols.split(",") if cols else DEFAULT_COLUMNS
            grouped = {c: [] for c in columns}
            for t in task_by_plan.get(pid, []):
                grouped.setdefault(t["status"], []).append(t)
            boards.append(
                {"plan_id": pid, "name": name, "columns": columns, "tasks": grouped}
            )
        return PlanBoardResponse(req_id=msg.id, boards=boards)
