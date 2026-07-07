# Planning

Plans and tasks are the building blocks of agent-driven workflows — define a plan, add tasks with statuses, move them through a kanban board, and track progress. In the A2E model, every plan operation is a typed `planning/*` message, making task management auditable, filterable, and swappable across backends.

## Overview

The **planning** capability provides a generic planning primitive — plans with tasks, configurable column vocabularies, and a kanban board view. A *kanban board* is just one concrete view of a plan: tasks grouped by their `status` column. Other planning schemes (waterfall phases, OKR trees, sprints) reuse the same task/status model with different vocabularies.

The planning capability is generic enough to back both agent task management and RL environment loop task tracking.

## Protocol Messages (6 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `planning/plan/create` | `PlanCreateRequest` | Agent → Host |
| `planning/plan/list` | `PlanListRequest` | Agent → Host |
| `planning/task/add` | `TaskAddRequest` | Agent → Host |
| `planning/task/update` | `TaskUpdateRequest` | Agent → Host |
| `planning/task/list` | `TaskListRequest` | Agent → Host |
| `planning/plan/board` | `PlanBoardRequest` | Agent → Host |

## Key Models

### PlanCreateRequest

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `"default"` | Plan display name |
| `columns` | `list[str]` | `[]` | Column vocabulary (empty = `["backlog", "todo", "in_progress", "done"]`) |
| `description` | `str` | `""` | Plan description |

### TaskAddRequest

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `plan_id` | `str` | — | Parent plan ID |
| `title` | `str` | — | Task title |
| `status` | `str` | `"backlog"` | Task status (must be a valid column) |
| `description` | `str` | `""` | Task description |
| `assignee` | `str` | `""` | Assigned user/agent |
| `deps` | `list[str]` | `[]` | Task IDs this depends on |
| `metadata` | `dict` | `{}` | Arbitrary key-value metadata |

### TaskUpdateRequest

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `plan_id` | `str` | — | Parent plan ID |
| `task_id` | `str` | — | Task ID to update |
| `status` | `str` | `""` | New status (empty = no change) |
| `assignee` | `str` | `""` | New assignee |
| `deps` | `list[str]` | `[]` | New dependency list |

### PlanBoardResponse

Returns a **board view** — tasks grouped by status column:

| Field | Type | Description |
|-------|------|-------------|
| `boards` | `list[dict]` | One board per plan, each with `plan_id`, `name`, `columns`, `tasks` |

Each board's `tasks` is a dict mapping column names to task lists: `{"backlog": [...], "todo": [...], ...}`.

## Default Column Vocabulary

```python
DEFAULT_COLUMNS = ["backlog", "todo", "in_progress", "done"]
```

Plans may override this with a custom vocabulary at creation time.

## Plugin

The `HermesPlanningPlugin` (`a2e/caps/planning/plugin.py`) extends `A2EPlugin` directly:

- Stores plans and tasks in SQLite
- Thread-safe (`threading.RLock`) for concurrent access
- Supports the full 6-message protocol
- Configurable `ROOT` path for the SQLite database location

## Client API

The harness `AgentRuntime` exposes planning methods:

```python
# Create a plan
plan = rt.plan_create(name="release", description="ship it")
plan_id = plan["plan_id"]

# Add tasks
t1 = rt.task_add(plan_id=plan_id, title="write spec", status="todo")
t2 = rt.task_add(plan_id=plan_id, title="implement", status="backlog")

# Kanban board view
board = rt.plan_board(plan_id=plan_id)
# board["boards"][0]["tasks"] -> {"backlog": [...], "todo": [...], "in_progress": [...], "done": [...]}

# Move a task
rt.task_update(plan_id=plan_id, task_id=t2["task_id"], status="in_progress")

# List tasks
tasks = rt.task_list(plan_id=plan_id)
tasks = rt.task_list(status="backlog")
```

## Key Design Points

- **Kanban is a view, not a separate capability** — the board message groups tasks by their `status` column. The same task/status model supports waterfall, OKR, sprints, or any column-based scheme.
- **SQLite storage** — the plugin uses a local SQLite database. The `ROOT` config option controls where `planning.db` is created.
- **No streaming** — planning operations are synchronous request/response with no streaming events.
- **Thread-safe** — the plugin uses a reentrant lock for database access.