# Subagents

```text
a2e/caps/subagents/protocol.py — 12 message types, SubagentConfig, TaskDefinition, SubagentInfo
a2e/caps/subagents/plugin.py   — SubagentPlugin, SubagentRuntime
a2e/caps/subagents/client.py   — SubagentClient
```

## Overview

The **subagents** capability provides multi-agent orchestration — spawning, delegating tasks to, communicating with, and merging results from child agents. Subagents run as independent agent instances with their own model, system prompt, capabilities, and execution scope.

Key concepts:
- **Spawn** — Create a new subagent with a specific configuration
- **Delegate** — Assign a task to a spawned subagent
- **Await** — Block until a subagent completes its task
- **Message** — Send inter-agent messages between subagents
- **Merge** — Combine results from multiple subagents
- **Cancel/Terminate** — Stop a running subagent gracefully or forcefully

## Isolation Model

Each subagent operates within a configurable isolation boundary:

### Memory Scope

| Scope | Description | Use Case |
|-------|-------------|----------|
| `shared` | Subagent shares parent's memory | Collaborative tasks needing shared context |
| `isolated` | Subagent has its own memory namespace | Independent tasks with no cross-contamination |
| `snapshot` | Subagent gets a copy of parent's memory at spawn time | Tasks that need initial context but produce independent results |

### Tool Scope

| Scope | Description | Use Case |
|-------|-------------|----------|
| `shared` | Full access to parent's tools | Trusted subagents that need all capabilities |
| `restricted` | Limited tool access (host policy) | Default — safe for most tasks |
| `isolated` | Completely separate tool namespace | Sandboxed execution with custom tool sets |

## Protocol Messages (12 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `SUBAGENT_SPAWN_REQ` | `SubagentSpawnRequest` | Parent → Host |
| `SUBAGENT_SPAWN_RESP` | `SubagentSpawnResponse` | Host → Parent |
| `SUBAGENT_DELEGATE_REQ` | `SubagentDelegateRequest` | Parent → Host |
| `SUBAGENT_DELEGATE_RESP` | `SubagentDelegateResponse` | Host → Parent |
| `SUBAGENT_AWAIT_REQ` | `SubagentAwaitRequest` | Parent → Host |
| `SUBAGENT_AWAIT_RESP` | `SubagentAwaitResponse` | Host → Parent |
| `SUBAGENT_MESSAGE_REQ` | `SubagentMessageRequest` | Agent → Host |
| `SUBAGENT_MESSAGE_RESP` | `SubagentMessageResponse` | Host → Sender |
| `SUBAGENT_LIST_REQ` | `SubagentListRequest` | Agent → Host |
| `SUBAGENT_LIST_RESP` | `SubagentListResponse` | Host → Agent |
| `SUBAGENT_CANCEL_REQ` | `SubagentCancelRequest` | Agent → Host |
| `SUBAGENT_TERMINATE_REQ` | `SubagentTerminateRequest` | Agent → Host |
| `SUBAGENT_MERGE_REQ` | `SubagentMergeRequest` | Agent → Host |
| `SUBAGENT_MERGE_RESP` | `SubagentMergeResponse` | Host → Agent |
| `SUBAGENT_EVENT` | `SubagentEvent` | Host → Agent (streaming) |

### SubagentConfig

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | Yes | — | Subagent name |
| `role` | `str` | No | `None` | Role descriptor |
| `model` | `str` | Yes | — | LLM model identifier |
| `system_prompt` | `str` | No | `None` | Custom system prompt |
| `capabilities` | `list[str]` | No | `[]` | Enabled capabilities |
| `memory_scope` | `MemoryScope` | No | `shared` | Memory isolation level |
| `tool_scope` | `ToolScope` | No | `restricted` | Tool access level |
| `max_steps` | `int` | No | `40` | Maximum agent steps |
| `timeout_seconds` | `int` | No | `600` | Execution timeout |
| `metadata` | `dict` | No | `{}` | Additional metadata |

### TaskDefinition

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | Yes | — | Task name |
| `instruction` | `str` | Yes | — | Task instruction for the subagent |
| `success_criteria` | `list[str]` | No | `[]` | Criteria for task completion |
| `metadata` | `dict` | No | `{}` | Additional task metadata |

### SubagentInfo

| Field | Type | Description |
|-------|------|-------------|
| `subagent_id` | `str` | Subagent identifier |
| `name` | `str` | Display name |
| `status` | `SubagentStatus` | Current status |
| `parent_agent_id` | `str` or `None` | Parent agent |
| `root_agent_id` | `str` or `None` | Root agent |
| `depth` | `int` | Nesting depth |
| `config` | `SubagentConfig` | Full configuration |

### SubagentStatus

| Value | Description |
|-------|-------------|
| `READY` | Spawned but not yet executing a task |
| `RUNNING` | Actively executing a delegated task |
| `WAITING` | Waiting for input or another subagent |
| `COMPLETED` | Task finished successfully |
| `FAILED` | Task finished with error |
| `CANCELLED` | Task was gracefully cancelled |
| `TERMINATED` | Task was forcefully terminated |

### Merge Strategies

| Strategy | Description |
|----------|-------------|
| `hierarchical_summary` | Parent summarizes child results |
| `voting` | Majority vote across results |
| `custom` | Host-defined merge strategy |

## SubagentPlugin

```python
from a2e.caps.subagents.plugin import SubagentPlugin, SubagentRuntime

class SubagentPlugin:
    def __init__(self):
        self.subagents: Dict[str, SubagentRuntime] = {}

    async def spawn(self, request: SubagentSpawnRequest) -> SubagentSpawnResponse: ...
    async def delegate(self, request: SubagentDelegateRequest) -> SubagentDelegateResponse: ...
    async def await_result(self, subagent_id: str) -> SubagentAwaitResponse: ...
    async def list_subagents(self) -> list[SubagentInfo]: ...
    async def terminate(self, subagent_id: str) -> None: ...
```

### SubagentRuntime

Each subagent is managed by a `SubagentRuntime` instance:

| Field | Type | Description |
|-------|------|-------------|
| `subagent_id` | `str` | Unique identifier |
| `config` | `SubagentConfig` | Configuration |
| `parent_agent_id` | `str` or `None` | Parent reference |
| `root_agent_id` | `str` or `None` | Root reference |
| `depth` | `int` | Nesting depth |
| `status` | `SubagentStatus` | Current status |
| `result` | `dict` or `None` | Task result |
| `task_handle` | `asyncio.Task` or `None` | Running task handle |

### Lifecycle

1. **Spawn**: Create runtime, set status = `READY`
2. **Delegate**: Create `asyncio.Task` for `run_task()`, set status = `RUNNING`
3. **Execute**: Agent adapter runs the task
4. **Complete**: Set status = `COMPLETED`, store result
5. **Fail**: Set status = `FAILED`, store error
6. **Cancel**: Cancel `asyncio.Task`, set status = `CANCELLED`
7. **Terminate**: Cancel `asyncio.Task`, set status = `TERMINATED`

## SubagentClient (Client)

```python
from a2e.caps.subagents.client import SubagentClient

subagents = SubagentClient(transport)

# Spawn a new subagent
spawn_resp = await subagents.spawn(
    name="researcher",
    model="claude-3.5-sonnet",
    role="research",
    system_prompt="You are a research assistant",
    capabilities=["tools", "memory"],
)

# Delegate a task
delegate_resp = await subagents.delegate(
    subagent_id=spawn_resp.subagent_id,
    task_name="research_topic",
    instruction="Research the latest developments in quantum computing",
    success_criteria=["Include at least 3 recent papers"],
)

# Await the result
result = await subagents.await_result(spawn_resp.subagent_id)
print(result.status)   # "COMPLETED"
print(result.result)   # {"summary": "...", "papers": [...]}

# Convenience: spawn + delegate + await in one call
result = await subagents.run(
    name="coder",
    model="gpt-4",
    task_name="implement_feature",
    instruction="Implement the login API endpoint",
)
```

### Convenience Method

| Method | Description |
|--------|-------------|
| `run(name, model, task_name, instruction)` | Spawn + delegate + await in one call |

## Security Considerations

1. **Depth limiting**: Host must enforce maximum nesting depth to prevent recursive spawning
2. **Memory isolation**: `isolated` and `snapshot` scopes prevent cross-agent data leakage
3. **Tool restriction**: `restricted` and `isolated` scopes limit dangerous tool access
4. **Timeout enforcement**: `timeout_seconds` prevents runaway subagents
5. **Step limiting**: `max_steps` prevents infinite agent loops
6. **Cancellation propagation**: Cancel requests must propagate to all child subagents
7. **Resource quotas**: Host should enforce per-session subagent count limits

See [Security & Trust](/resources/security-trust) for the full security model.

## Relationship to Other Capabilities

- **memory**: `memory_scope` controls whether subagents share, isolate, or snapshot parent memory
- **tools**: `tool_scope` controls tool access; `restricted` subagents see a filtered tool list
- **chains**: Chains orchestrate tools/data within one agent; subagents orchestrate across multiple agents
- **mcp**: Subagents with `shared` tool scope can access MCP-bridged tools

For a complete walkthrough of building a subagent orchestration plugin and client, see [Subagent Orchestrator (Plugin & Client)](/cookbook/subagent-orchestrator).
