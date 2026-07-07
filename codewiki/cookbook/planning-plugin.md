# Planning Plugin & Client Example

```text
a2e/caps/planning/plugin.py  — HermesPlanningPlugin
a2e/caps/planning/protocol.py — PlanCreateRequest, TaskAddRequest, PlanBoardResponse, …
harness/agent_runtime.py      — plan_create(), task_add(), plan_board(), …
```

## Overview

This cookbook covers the **planning** capability — plans with tasks, configurable column vocabularies, and a kanban board view. You'll learn how to:

1. **Plugin side**: Run the `HermesPlanningPlugin` from a YAML config
2. **Client side**: Create plans, add tasks, move them through columns, and view the kanban board

## Plugin Side: HermesPlanningPlugin

The `HermesPlanningPlugin` is a complete, production-ready planning plugin that stores plans and tasks in SQLite. It extends `A2EPlugin` directly and handles all six `planning/*` message types.

### Config Registration

```yaml
plugins:
  - name: planning
    type: planning
    cls: a2e.caps.planning.plugin.HermesPlanningPlugin
    metadata:
      enabled: true
      priority: 0
      exclusive: false
      ROOT: "/tmp/a2e/cookbook/planning"
```

The `ROOT` metadata key controls where the `planning.db` SQLite file is created.

### Starting the Host

```python
# cookbook/servers/planning/planning_server.py
import logging
import time
from a2e.schema import A2EHostConfig
from a2e.core.transports import build_transport
from a2e.server import A2EServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    import yaml
    with open("cookbook/servers/planning/config.yaml") as f:
        config = A2EHostConfig(**yaml.safe_load(f))

    transport = build_transport(config.transport, logger)
    server = A2EServer(config=config, transport=transport, logger=logger)

    try:
        server.start()
        logger.info("Planning server running on %s:%s",
                     config.server.host, config.server.port)
        while transport.alive():
            time.sleep(0.5)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
```

## Client Side: Planning Usage

The harness `AgentRuntime` provides convenience methods for all planning operations. Each example below assumes you have a connected `AgentRuntime` instance (`rt`) with `"planning"` in its `agent_caps`.

### 1. Basic Setup — Connect and Create a Plan

```python
from harness.agent_runtime import AgentRuntime

rt = AgentRuntime("http://localhost:8766", agent_caps=["planning"])
rt.connect()
print("Negotiated caps:", [c.value for c in rt.caps])
# Output: Negotiated caps: ['planning']

# Create a plan with default kanban columns
plan = rt.plan_create(name="release", description="ship v2.0")
print(f"Created plan: {plan['plan_id']} (success={plan['success']})")
# Output: Created plan: a1b2c3d4e5f6 (success=True)

# Create a plan with custom columns
sprint = rt.plan_create(
    name="sprint-7",
    columns=["icebox", "backlog", "in_progress", "review", "done"],
    description="Sprint 7 backlog",
)
print(f"Created sprint: {sprint['plan_id']} columns={sprint['columns']}")
# Output: Created sprint: ... columns=['icebox', 'backlog', 'in_progress', 'review', 'done']

rt.disconnect()
```

### 2. Add and List Tasks

```python
rt = AgentRuntime("http://localhost:8766", agent_caps=["planning"])
rt.connect()

# Create a plan
plan = rt.plan_create(name="website-redesign")
pid = plan["plan_id"]

# Add tasks at different statuses
t1 = rt.task_add(plan_id=pid, title="design mockups", status="todo")
t2 = rt.task_add(plan_id=pid, title="implement homepage", status="backlog")
t3 = rt.task_add(plan_id=pid, title="write copy", status="backlog", assignee="alice")
t4 = rt.task_add(plan_id=pid, title="deploy", status="backlog",
                 description="deploy to staging then prod",
                 deps=[t1["task_id"], t2["task_id"]])

print(f"Tasks: {t1['task_id']}, {t2['task_id']}, {t3['task_id']}, {t4['task_id']}")
# Output: Tasks: ..., ..., ..., ...

# List all tasks in the plan
tasks = rt.task_list(plan_id=pid)
print(f"Total tasks in plan: {len(tasks['tasks'])}")
# Output: Total tasks in plan: 4

# List only backlog tasks
backlog = rt.task_list(plan_id=pid, status="backlog")
print(f"Backlog tasks: {len(backlog['tasks'])}")
# Output: Backlog tasks: 3

rt.disconnect()
```

### 3. Update Task Status (Move Through Columns)

```python
rt = AgentRuntime("http://localhost:8766", agent_caps=["planning"])
rt.connect()

plan = rt.plan_create(name="kanban-demo")
pid = plan["plan_id"]

# Add tasks
t1 = rt.task_add(plan_id=pid, title="research", status="todo")
t2 = rt.task_add(plan_id=pid, title="implement", status="backlog")
t3 = rt.task_add(plan_id=pid, title="review", status="backlog")

# Move tasks through the kanban flow
rt.task_update(plan_id=pid, task_id=t1["task_id"], status="in_progress")
rt.task_update(plan_id=pid, task_id=t1["task_id"], status="done")
rt.task_update(plan_id=pid, task_id=t2["task_id"], status="in_progress")
rt.task_update(plan_id=pid, task_id=t3["task_id"], status="in_progress")

# Verify
done_tasks = rt.task_list(plan_id=pid, status="done")
inprog_tasks = rt.task_list(plan_id=pid, status="in_progress")
print(f"Done: {len(done_tasks['tasks'])}, In Progress: {len(inprog_tasks['tasks'])}")
# Output: Done: 1, In Progress: 2

rt.disconnect()
```

### 4. Kanban Board View

```python
rt = AgentRuntime("http://localhost:8766", agent_caps=["planning"])
rt.connect()

# Create a plan with tasks
plan = rt.plan_create(name="sprint-8")
pid = plan["plan_id"]

rt.task_add(plan_id=pid, title="auth module", status="done")
rt.task_add(plan_id=pid, title="API docs", status="in_progress")
rt.task_add(plan_id=pid, title="rate limiting", status="todo")
rt.task_add(plan_id=pid, title="caching layer", status="backlog")

# Get the kanban board
board = rt.plan_board(plan_id=pid)
b = board["boards"][0]

print(f"Plan: {b['name']}  Columns: {b['columns']}")
for col, tasks in b["tasks"].items():
    titles = [t["title"] for t in tasks]
    print(f"  {col}: {titles}")

# Output:
# Plan: sprint-8  Columns: ['backlog', 'todo', 'in_progress', 'done']
#   backlog: ['caching layer']
#   todo: ['rate limiting']
#   in_progress: ['API docs']
#   done: ['auth module']

# Get boards for all plans (empty plan_id)
all_boards = rt.plan_board()
print(f"Total boards: {len(all_boards['boards'])}")
# Output: Total boards: 1

rt.disconnect()
```

### 5. Error Handling

```python
rt = AgentRuntime("http://localhost:8766", agent_caps=["planning"])
rt.connect()

# Update a non-existent task
result = rt.task_update(plan_id="nonexistent", task_id="nope", status="done")
print(f"Update success: {result['success']}")
# Output: Update success: False

rt.disconnect()
```

### 6. Integration Pattern — Full Workflow

```python
rt = AgentRuntime("http://localhost:8766", agent_caps=["planning"])
rt.connect()

# 1. Create plan
plan = rt.plan_create(name="onboarding", columns=["todo", "in_progress", "done"])
pid = plan["plan_id"]

# 2. Add tasks
items = [
    ("create user guide", "todo"),
    ("implement tutorial", "todo"),
    ("add telemetry", "todo"),
    ("deploy to prod", "backlog", {"assignee": "ops"}),
]
for title, status, *rest in items:
    kwargs = rest[0] if rest else {}
    rt.task_add(plan_id=pid, title=title, status=status, **kwargs)

# 3. Process work
rt.task_update(plan_id=pid, task_id=..., status="in_progress")
rt.task_update(plan_id=pid, task_id=..., status="done")

# 4. Check board
board = rt.plan_board(plan_id=pid)
progress = {col: len(tasks) for col, tasks in board["boards"][0]["tasks"].items()}
print(f"Progress: {progress}")
# Output: Progress: {'todo': 2, 'in_progress': 1, 'done': 1}

rt.disconnect()
```

## Key Patterns

| Pattern | When to Use |
|---------|-------------|
| **Plan creation** | Start a new work unit with a configurable column vocabulary |
| **Task add** | Populate a plan with items at various statuses |
| **Task update** | Move a task through columns, change assignee, update deps |
| **Task list** | Query tasks by plan and/or status for filtering |
| **Kanban board** | Get the full grouped view — all tasks organized by column |

## Tips

- **Default columns** (`backlog`, `todo`, `in_progress`, `done`) work for most kanban workflows. Customize at plan creation time for different schemes (e.g., `["icebox", "backlog", "in_progress", "review", "done"]`).
- **Task dependencies** (`deps`) are advisory — the plugin does not enforce or validate them. Use them for display and workflow guidance.
- **Task metadata** (`metadata`) accepts arbitrary JSON. Use it for custom fields (priority, estimate, labels, etc.) without schema changes.
- **The `plan_board` with empty `plan_id`** returns boards for all plans — useful for dashboards.
- **Error handling** is straightforward: check `success` on responses. Failed updates return `success=False` without raising.
- **Thread safety**: The plugin uses `threading.RLock()`, so concurrent access from multiple agents is safe.