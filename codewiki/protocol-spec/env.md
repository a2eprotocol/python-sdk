# Environment Capability Specification

## Capability Identity

| Property | Value |
|----------|-------|
| Enum | `A2ECapability.ENV` |
| String | `"env"` |
| Plugin Type | `EnvPlugin` |
| Namespace | `env/*` |
| Message Count | 25 |

## Overview

The **environment** capability provides RL-style (Reinforcement Learning) step-wise interaction between Agent and Environment. It defines the core primitives for agentic loops: reset an episode, take a step, observe state, and receive rewards.

**Core primitives:**
- `reset` — Initialize a new episode, return initial state
- `step` — Execute action, receive (next_state, reward, done, info)
- `observe` — Read-only current state without acting

**Extended primitives:**
- `close` — Terminate an episode early
- `spaces` — Discover action/state space definitions
- `render` — Retrieve visual/multimodal representation
- `plan` — Get environment-suggested affordances/actions
- `batch_step` — Execute multiple steps in parallel

**Server-initiated:**
- `state/push` — Incremental state update pushed to agent

**Data plane (orthogonal to the episode lifecycle):**
- `data/reset` — Restore the data root to its pristine state
- `data/add` — Stage task data into the data root (metadata only; host moves bytes)
- `data/get` — Read artifacts back out of the data root

**Host extension:**
- `exp/list` — Pull the transitions the host recorded for an episode (host-implemented; not in the base plugin)

**Cross-capability integration:**
- Each `env/step` interaction can be auto-recorded as an (s, a, r, s', done) tuple in the ExperienceBuffer
- Reward signals can be forwarded to the learning subsystem (`learn/*`)
- Enables RL training loops, simulations, and CUA/browser environments

## Protocol Flow

```mermaid
sequenceDiagram
    participant A as Agent
    participant H as Host (EnvPlugin)

    A->>H: env/space/req {env_name}
    H->>A: env/space/resp {action_space, state_schema}

    Note over A,H: Data plane (orthogonal — runs between tasks)
    A->>H: env/data/reset/req {scope}
    H->>A: env/data/reset/resp {restored}
    A->>H: env/data/add/req {parts metadata}
    H->>A: env/data/add/resp {added, staged}

    A->>H: env/reset/req {env_name, seed, options}
    H->>A: env/reset/resp {obs: EnvObservation}

    loop Episode Loop
        A->>H: env/step/req {episode_id, action}
        H->>A: env/step/resp {obs: EnvObservation}
        opt State Push
            H->>A: env/state/push {delta, reward, terminal}
        end
    end

    A->>H: env/close/req {episode_id}
    H->>A: env/close/resp {closed}
```

## Message Types (25)

### Reset (2)

#### env/reset/req — EnvResetRequest

Agent → Host. Initialize a new episode.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/reset/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `env_name` | `str` | Yes | — | Environment identifier |
| `seed` | `int` | No | `None` | Random seed for reproducibility |
| `options` | `dict[str, Any]` | No | `{}` | Environment-specific options |

#### env/reset/resp — EnvResetResponse

Host → Agent. Returns initial observation.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/reset/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `req_id` | `str` | Yes | `""` | Echoes request ID |
| `obs` | `EnvObservation` | Yes | — | Initial observation |

### Step (2) — Core RL Primitive

#### env/step/req — EnvStepRequest

Agent → Host. Execute an action in the environment.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/step/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `episode_id` | `str` | Yes | — | Active episode identifier |
| `action` | `dict[str, Any]` | Yes | — | Action to execute |

#### env/step/resp — EnvStepResponse

Host → Agent. Returns observation after action.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/step/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `req_id` | `str` | Yes | `""` | Echoes request ID |
| `obs` | `EnvObservation` | Yes | — | Post-action observation |

### Observe (2) — Read-only State

#### env/observe/req — EnvObserveRequest

Agent → Host. Retrieve current state without acting.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/observe/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `episode_id` | `str` | Yes | — | Episode to observe |

#### env/observe/resp — EnvObserveResponse

Host → Agent. Returns current observation.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/observe/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `req_id` | `str` | Yes | `""` | Echoes request ID |
| `obs` | `EnvObservation` | Yes | — | Current observation |

### Close (2) — End Episode

#### env/close/req — EnvCloseRequest

Agent → Host. Terminate an episode early.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/close/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `episode_id` | `str` | Yes | — | Episode to close |

#### env/close/resp — EnvCloseResponse

Host → Agent.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/close/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `req_id` | `str` | Yes | `""` | Echoes request ID |
| `closed` | `bool` | Yes | `True` | Whether close succeeded |

### Spaces (2) — Action/State Discovery

#### env/space/req — EnvSpacesRequest

Agent → Host. Discover action and state space definitions.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/space/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `env_name` | `str` | Yes | — | Environment identifier |

#### env/space/resp — EnvSpacesResponse

Host → Agent.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/space/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `action_space` | `dict[str, Any]` | Yes | — | JSON Schema defining valid actions |
| `state_schema` | `dict[str, Any]` | Yes | — | JSON Schema defining state structure |

### Render (2) — Multimodal Support

#### env/render/req — EnvRenderRequest

Agent → Host. Retrieve visual/multimodal representation of current state.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/render/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `episode_id` | `str` | Yes | — | Episode to render |
| `mode` | `str` | No | `"screenshot"` | Render mode: `screenshot`, `rgb_array`, `text` |

#### env/render/resp — EnvRenderResponse

Host → Agent.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/render/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `render` | `Any` | Yes | — | Rendered output (bytes, base64, or structured) |

### Plan (2) — Affordance Discovery

#### env/plan/req — EnvPlanRequest

Agent → Host. Get environment-suggested actions.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/plan/resp"` | Message type (note: shares resp value) |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `episode_id` | `str` | No | `None` | Optional episode context |
| `state` | `dict[str, Any]` | No | `None` | Optional state context |

#### env/plan/resp — EnvPlanResponse

Host → Agent.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/plan/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `suggested_actions` | `list[dict[str, Any]]` | Yes | `[]` | Suggested actions with descriptions |

### Batch Step (2) — Parallel Execution

#### env/batch_step/req — EnvBatchStepRequest

Agent → Host. Execute multiple actions in parallel across episodes.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/batch_step/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `episode_ids` | `list[str]` | Yes | — | Episode identifiers |
| `actions` | `list[dict[str, Any]]` | Yes | — | Actions (1:1 with episode_ids) |

#### env/batch_step/resp — EnvBatchStepResponse

Host → Agent.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/batch_step/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `results` | `list[EnvStepResponse]` | Yes | — | Results (1:1 with request) |

### State Push (1) — Server-initiated

#### env/state/push — EnvStatePush

Host → Agent (server-initiated). Incremental environment state update.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/state/push"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `episode_id` | `str` | Yes | — | Episode identifier |
| `step_id` | `int` | Yes | — | Step number |
| `action_id` | `str` | No | `None` | Tie to specific EnvAction |
| `event_type` | `str` | Yes | — | `Observation`, `tool_result`, `status`, `error` |
| `reason` | `str` | No | `""` | Reason: `"proc_exit"`, `"oom_warning"`, etc. |
| `delta` | `dict[str, Any]` | No | `{}` | Sparse diff (only changed fields) |
| `reward` | `float` | No | `None` | Optional reward signal |
| `reward_info` | `dict` | No | `{}` | Additional reward metadata |
| `terminal` | `bool` | No | `False` | Marks episode termination |

**State push use cases:**
- Async tool completion
- External world changes (filesystem, browser DOM)
- Long-running process updates
- Safety/system signals (OOM, timeout)

### Experience List (2) — Recorded Transitions

A **host extension** (wire-compatible with `xa-agent-env`) for pulling the transitions a host recorded during an episode — the `(state, action, reward, …)` tuples a training loop consumes. Neither the base `EnvPlugin` nor `EnvAPI` implements these; a host that records transitions opts in by handling the two messages itself.

#### env/exp/list/req — EnvExpListRequest

Agent → Host. Pull recorded transitions.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/exp/list/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `episode_id` | `str` | No | `""` | Restrict to one episode (empty ⇒ all) |
| `limit` | `int` | No | `100` | Maximum transitions to return |

#### env/exp/list/resp — EnvExpListResponse

Host → Agent. Recorded experiences for an episode (or all).

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/exp/list/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `req_id` | `str` | Yes | `""` | Echoes request ID |
| `episodes` | `list[dict]` | No | `[]` | Recorded transitions |

### Data Plane (6) — Task Data Lifecycle

The data plane is **orthogonal to the episode lifecycle**. `env/reset` starts an *episode*; the `env/data/*` messages move task data into and out of the env's **data root** (default `/workspace/data`). A host may reset an episode without touching data, and restore data without starting an episode.

**Payloads carry METADATA ONLY — bytes never cross the wire.** At multi-GB scale the host performs a local filesystem operation inside the container (bind-mounted path, archive extraction, …), so no large payload is ever buffered in a protocol message.

#### env/data/reset/req — EnvDataResetRequest

Agent → Host. Restore the data plane to its **pristine** state. This is *not* an episode reset and *not* a purge-to-empty: the host restores whatever it considers pristine (typically clearing the data root and re-staging the env's baseline corpus). A host with no baseline simply empties the root and reports `restored: 0`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/data/reset/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `scope` | `str` | No | `"all"` | `all` restores the whole root; `baseline` re-stages only the pristine corpus |
| `data_root` | `str` | No | `/workspace/data` | Data root to restore |

#### env/data/reset/resp — EnvDataResetResponse

Host → Agent. Data plane restored. `req_id` is required for RPC match.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/data/reset/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `req_id` | `str` | Yes | `""` | Echoes request ID |
| `ok` | `bool` | Yes | `True` | Whether restore succeeded |
| `restored` | `int` | No | `0` | Number of items re-staged to reach the pristine state |
| `data_root` | `str` | No | `/workspace/data` | Data root restored |
| `detail` | `str` | No | `""` | Host-supplied detail |

#### env/data/add/req — EnvDataAddRequest

Agent → Host. Stage task data into the data root before an episode. Each `parts` entry is an `EnvDataPart` (metadata only).

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/data/add/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `parts` | `list[EnvDataPart]` | No | `[]` | Items to stage (metadata only) |
| `data_root` | `str` | No | `/workspace/data` | Data root to stage into |

#### env/data/add/resp — EnvDataAddResponse

Host → Agent. What was staged. Failures are **per-part, never fatal**.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/data/add/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `req_id` | `str` | Yes | `""` | Echoes request ID |
| `ok` | `bool` | Yes | `True` | `False` when any part failed |
| `added` | `int` | No | `0` | Number of items successfully staged |
| `errors` | `list[str]` | No | `[]` | Per-part failure messages |
| `staged` | `list[dict]` | No | `[]` | Echo of each staged item (`uri`/`dest`/`size_bytes`/`checksum`) |

#### env/data/get/req — EnvDataGetRequest

Agent → Host. Read items back **out** of the data root — the graded artifact-collection path. The host lists matching entries; `content` is only populated when the caller asks for it **and** the item is within the size cap.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/data/get/req"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `query` | `str` | No | `""` | Glob/substring relative to the data root (empty lists everything) |
| `include_content` | `bool` | No | `False` | Inline file contents; the host MUST refuse above its size cap |
| `max_bytes` | `int` | No | `1048576` | Per-item ceiling when `include_content` is set (default 1 MiB) |
| `data_root` | `str` | No | `/workspace/data` | Data root to read from |

#### env/data/get/resp — EnvDataGetResponse

Host → Agent. Items read back from the data root. Each item is `{uri, dest, size_bytes, checksum, mime, content?}`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `str` | Yes | `"env/data/get/resp"` | Message type |
| `id` | `str` | Yes | auto | Message UUID |
| `version` | `str` | Yes | `"1.0"` | Protocol version |
| `ts` | `float` | Yes | auto | Timestamp |
| `req_id` | `str` | Yes | `""` | Echoes request ID |
| `ok` | `bool` | Yes | `True` | Whether the read succeeded |
| `items` | `list[dict]` | No | `[]` | Matching items |
| `truncated` | `bool` | No | `False` | An inlined item hit the `max_bytes` cap |
| `detail` | `str` | No | `""` | Host-supplied detail |

#### EnvDataPart

One staged item. Bytes live on the host filesystem, never on the wire. Declared with `extra="allow"`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `src` | `str` | No | `""` | Host-side source the host copies from (bind-mount, archive, …) |
| `dest` | `str` | No | `""` | Path relative to the data root; empty means the part's own name |
| `uri` | `str` | No | `""` | Logical identifier, recorded and echoed back (not dereferenced by the SDK) |
| `checksum` | `str` | No | `""` | `sha256:<hex>` verified by the host after staging (empty skips verification) |
| `size_bytes` | `int` | No | `None` | Size of the staged item |
| `mime` | `str` | No | `""` | Optional MIME type |

## Data Models

### EnvState

Flexible state container with `extra="allow"` — accepts any fields the environment provides.

### EnvObservation

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `episode_id` | `str` | Yes | — | Episode this observation belongs to |
| `step_num` | `int` | Yes | — | Step number within episode |
| `state` | `EnvState` | Yes | — | Environment state |
| `done` | `bool` | No | `False` | Episode is complete |
| `truncated` | `bool` | No | `False` | Episode was truncated (time limit) |
| `reward` | `float` | No | `0.0` | Reward signal |
| `created_at` | `float` | No | auto | Observation timestamp |
| `metadata` | `dict[str, Any]` | No | `{}` | Additional metadata |

### EnvAction

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `action_type` | `str` | Yes | — | Action type identifier |
| `payload` | `dict[str, Any]` | No | `{}` | Action payload |
| `metadata` | `dict[str, Any]` | No | `{}` | Additional metadata |

### EnvEvent

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `event_id` | `str` | No | auto UUID | Event identifier |
| `type` | `str` | Yes | — | Event type |
| `episode_id` | `str` | Yes | — | Episode context |
| `step_id` | `int` | Yes | — | Step context |
| `action_id` | `str` | No | `None` | Tie to EnvAction |
| `payload` | `dict[str, Any]` | No | `{}` | Event payload |
| `timestamp` | `float` | No | auto | Event timestamp |
| `metadata` | `dict[str, Any]` | No | `{}` | Additional metadata |

## Error Codes — EnvErrorCode

| Code | Enum Value | Description | Retryable |
|------|------------|-------------|-----------|
| `runtime_error` | `RUNTIME_ERROR` | General runtime failure | Depends |
| `unknown_action` | `UNKNOWN_ACTION` | Action type not recognized | No |
| `reset_denied` | `RESET_DENIED` | Environment refused reset | No |

## Wire Examples

### Reset and Step Loop

```json
{"type":"env/reset/req","id":"er1","version":"1.0","ts":1716123456.789,"env_name":"browser","seed":42,"options":{"url":"https://example.com"}}
```

```json
{"type":"env/reset/resp","id":"er2","version":"1.0","ts":1716123457.100,"req_id":"er1","obs":{"episode_id":"ep_abc","step_num":0,"state":{"url":"https://example.com","title":"Example"},"done":false,"truncated":false,"reward":0.0}}
```

```json
{"type":"env/step/req","id":"es1","version":"1.0","ts":1716123458.100,"episode_id":"ep_abc","action":{"action_type":"click","payload":{"selector":"#button"}}}
```

```json
{"type":"env/step/resp","id":"es2","version":"1.0","ts":1716123458.500,"req_id":"es1","obs":{"episode_id":"ep_abc","step_num":1,"state":{"url":"https://example.com/result","title":"Result"},"done":false,"truncated":false,"reward":1.0}}
```

### State Push (Server-initiated)

```json
{"type":"env/state/push","id":"sp1","version":"1.0","ts":1716123459.100,"episode_id":"ep_abc","step_id":1,"action_id":"act_1","event_type":"tool_result","reason":"proc_exit","delta":{"stdout":"done"},"reward":0.5,"terminal":false}
```

### Data Plane (Metadata Only)

```json
{"type":"env/data/add/req","id":"da1","version":"1.0","ts":1716123460.100,"data_root":"/workspace/data","parts":[{"src":"/host/tasks/task-B/orders.csv","dest":"orders.csv","uri":"orders","checksum":"sha256:9f2a...","mime":"text/csv"}]}
```

```json
{"type":"env/data/add/resp","id":"da2","version":"1.0","ts":1716123460.400,"req_id":"da1","ok":true,"added":1,"errors":[],"staged":[{"uri":"orders","dest":"orders.csv","size_bytes":18432}]}
```

```json
{"type":"env/data/get/req","id":"dg1","version":"1.0","ts":1716123470.100,"query":"*.csv","include_content":false,"max_bytes":1048576,"data_root":"/workspace/data"}
```

```json
{"type":"env/data/get/resp","id":"dg2","version":"1.0","ts":1716123470.300,"req_id":"dg1","ok":true,"items":[{"uri":"orders.csv","dest":"orders.csv","size_bytes":18432,"checksum":"sha256:9f2a..."}],"truncated":false}
```

## Security Considerations

1. **Episode isolation**: Episodes must be scoped to prevent cross-session leakage
2. **Action validation**: Actions must conform to action_space schema
3. **State push gating**: Only emitted if agent negotiated `env_push` capability
4. **Batch limits**: Host should enforce maximum batch_step size
5. **Reward signal integrity**: Reward values must not be tamperable by the agent
6. **Data-root confinement**: `data_root`/`dest`/`src` are host-interpreted paths — the host must confine them to the intended data root and reject traversal (`..`), never copying from or to arbitrary host paths
7. **No bytes on the wire**: `env/data/*` payloads are metadata only; the host performs file I/O locally. The `data_get` `include_content` path is the sole exception and must enforce `max_bytes`
