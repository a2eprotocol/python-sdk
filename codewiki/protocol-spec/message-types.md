# Message Types

```text
a2e/caps/base/protocol.py          — Base types (7)
a2e/caps/tools/protocol.py        — Tool types (5)
a2e/caps/memory/protocol.py       — Memory types (6)
a2e/caps/env/protocol.py          — Environment types (14)
a2e/caps/proc/protocol.py        — Process types (8)
a2e/caps/learn/protocol.py       — Learning types (8)
a2e/caps/skills/protocol.py      — Skill types (5)
a2e/caps/toolkits/protocol.py    — Toolkit types (4)
a2e/caps/chains/protocol.py      — Chain types (3)
a2e/caps/mcp/protocol.py         — MCP types (19)
```

## Complete Type Index

### Core Types (7)

| Type String | Model | Direction | Description |
|-------------|-------|-----------|-------------|
| `handshake/req` | `HandshakeRequest` | A→H | Session initiation |
| `handshake/resp` | `HandshakeResponse` | H→A | Handshake result |
| `invoke/event` | `A2EEvent` | H→A | Streaming event |
| `ping` | `Ping` | A→H | Liveness check |
| `pong` | `Pong` | H→A | Ping response |
| `shutdown` | `Shutdown` | A→H | Graceful termination |
| `error` | `A2EError` | H→A | Error response |

### Tools (5)

| Type String | Model | Description |
|-------------|-------|-------------|
| `tool/list/req` | `ToolListRequest` | List available tools |
| `tool/list/resp` | `ToolListResponse` | Tool list result |
| `tool/call/req` | `ToolCallRequest` | Execute a tool |
| `tool/call/resp` | `ToolCallResponse` | Tool execution result |
| `tool/event` | `ToolEvent` | Streaming tool event |

### Memory (6)

| Type String | Model | Description |
|-------------|-------|-------------|
| `memory/store/req` | `MemoryStoreRequest` | Store memory entries |
| `memory/store/resp` | `MemoryStoreResponse` | Store result |
| `memory/retrieve/req` | `MemoryRetrieveRequest` | Retrieve from memory |
| `memory/retrieve/resp` | `MemoryRetrieveResponse` | Retrieved entries |
| `memory/forget/req` | `MemoryForgetRequest` | Delete from memory |
| `memory/forget/resp` | `MemoryForgetResponse` | Deletion count |

### Environment (14)

| Type String | Model | Description |
|-------------|-------|-------------|
| `env/reset/req` | `EnvResetRequest` | Reset environment |
| `env/reset/resp` | `EnvResetResponse` | Reset result |
| `env/step/req` | `EnvStepRequest` | Take a step |
| `env/step/resp` | `EnvStepResponse` | Step result |
| `env/observe/req` | `EnvObserveRequest` | Observe state |
| `env/observe/resp` | `EnvObserveResponse` | Observation |
| `env/close/req` | `EnvCloseRequest` | Close environment |
| `env/close/resp` | `EnvCloseResponse` | Close result |
| `env/spaces/req` | `EnvSpacesRequest` | Get action/state spaces |
| `env/spaces/resp` | `EnvSpacesResponse` | Space schemas |
| `env/render/req` | `EnvRenderRequest` | Render environment |
| `env/render/resp` | `EnvRenderResponse` | Rendered output |
| `env/plan/req` | `EnvPlanRequest` | Get affordances |
| `env/plan/resp` | `EnvPlanResponse` | Suggested actions |
| `env/batch_step/req` | `EnvBatchStepRequest` | Parallel steps |
| `env/batch_step/resp` | `EnvBatchStepResponse` | Batch results |
| `env/state_push` | `EnvStatePush` | Server-initiated push |

### Processes (8)

| Type String | Model | Description |
|-------------|-------|-------------|
| `proc/spawn/req` | `ProcSpawnRequest` | Start a process |
| `proc/spawn/resp` | `ProcSpawnResponse` | Spawn result |
| `proc/write/req` | `ProcWriteRequest` | Write to stdin |
| `proc/write/resp` | `ProcWriteResponse` | Write result |
| `proc/read/event` | `ProcReadEvent` | Stdout/stderr output |
| `proc/kill/req` | `ProcKillRequest` | Kill process |
| `proc/kill/resp` | `ProcKillResponse` | Kill result |
| `proc/status/req` | `ProcStatusRequest` | Query status |
| `proc/status/resp` | `ProcStatusResponse` | Status info |

### Learning (8)

| Type String | Model | Description |
|-------------|-------|-------------|
| `learn/feedback/req` | `LearnFeedbackRequest` | Submit feedback |
| `learn/feedback/resp` | `LearnFeedbackResponse` | Feedback result |
| `learn/experience/req` | `LearnExperienceRequest` | Record RL experience |
| `learn/experience/resp` | `LearnExperienceResponse` | Experience stored |
| `learn/adapt/req` | `LearnAdaptRequest` | Trigger adaptation |
| `learn/adapt/resp` | `LearnAdaptResponse` | Adapted records |
| `learn/stats/req` | `LearnStatsRequest` | Query stats |
| `learn/stats/resp` | `LearnStatsResponse` | Performance data |

### Skills (5)

| Type String | Model | Description |
|-------------|-------|-------------|
| `skill/discover/req` | `SkillDiscoverRequest` | Discover skills |
| `skill/discover/resp` | `SkillDiscoverResponse` | Skill list |
| `skill/call/req` | `SkillCallRequest` | Execute a skill |
| `skill/call/resp` | `SkillCallResponse` | Skill result |
| `skill/event` | `SkillEvent` | Streaming skill event |

### Toolkits (4)

| Type String | Model | Description |
|-------------|-------|-------------|
| `toolkit/list/req` | `ToolkitListRequest` | List toolkits |
| `toolkit/list/resp` | `ToolkitListResponse` | Toolkit list |
| `toolkit/configure/req` | `ToolkitConfigureRequest` | Configure a toolkit |
| `toolkit/configure/resp` | `ToolkitConfigureResponse` | Configuration result |

### Chains (3)

| Type String | Model | Description |
|-------------|-------|-------------|
| `chain/req` | `ChainRequest` | Execute a chain DAG |
| `chain/resp` | `ChainResponse` | Chain result |
| `chain/event` | `ChainEvent` | Node execution event |

### MCP (19)

| Type String | Description |
|-------------|-------------|
| `mcp/server/register/req` | Register MCP server |
| `mcp/server/register/resp` | Registration result |
| `mcp/server/list/req` | List MCP servers |
| `mcp/server/list/resp` | Server list |
| `mcp/server/unregister/req` | Unregister server |
| `mcp/server/unregister/resp` | Unregister result |
| `mcp/server/push` | Server-initiated notification |
| `mcp/resource/list/req` | List resources |
| `mcp/resource/list/resp` | Resource list |
| `mcp/resource/read/req` | Read a resource |
| `mcp/resource/read/resp` | Resource content |
| `mcp/resource/subscribe/req` | Subscribe to resource |
| `mcp/resource/subscribe/resp` | Subscription result |
| `mcp/prompt/list/req` | List prompts |
| `mcp/prompt/list/resp` | Prompt list |
| `mcp/prompt/get/req` | Get a prompt |
| `mcp/prompt/get/resp` | Prompt content |
| `mcp/sampling/req` | LLM sampling request (server→agent) |
| `mcp/sampling/resp` | LLM sampling response (agent→server) |

## Total: 79 message types across 10 namespaces
