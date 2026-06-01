# Configuration

## A2EHostConfig

The central configuration object, loaded from YAML:

```python
from a2e.schema import A2EHostConfig
config = A2EHostConfig.from_yaml("config.yaml")
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host_id` | `str` | UUID hex[:8] | Unique host identifier |
| `server` | `ServerConfig` | `0.0.0.0:8765` | Server host and port |
| `auth_token` | `str` | `""` | Authentication token for agents |
| `transport` | `TransportConfig` | — | Transport type and settings |
| `audit` | `AuditConfig` | — | Audit logging configuration |
| `plugins` | `list[PluginConfig]` | `[]` | Plugin configurations |
| `snapshot_store` | `SnapshotStoreConfig` | None | Persistence store config |
| `snapshot_mode` | `str` | `"host"` | `"host"` / `"plugin"` / `"hybrid"` |
| `audit_log_path` | `str` | None | Path to audit log file |
| `global_limits` | `dict` | `{}` | Resource limits |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_plugin(name)` | `PluginConfig` or `None` | Find plugin config by name |
| `enabled_plugins()` | `list[PluginConfig]` | Filter to enabled plugins only |

## Complete YAML Example

```yaml
host_id: "a2e-dev"
server:
  host: "0.0.0.0"
  port: 8765
auth_token: "dev-secret"

transport:
  type: http
  config:
    base_url: "http://localhost:8765"
    send_path: "/send"
    stream_path: "/stream"

audit:
  enabled: true
  path: "/tmp/a2e-audit.jsonl"
  rotate:
    max_bytes: 10485760    # 10 MB
    backup_count: 5
  session_id_source: "uuid"  # "host_id" or "uuid"

snapshot_store:
  type: file
  config:
    root: "/tmp/a2e-snapshots"

snapshot_mode: "hybrid"

plugins:
  # --- Tools ---
  - name: mytools
    type: tools
    cls: cookbook.servers.tools.registry_tool_plugin.RegistryToolPlugin
    metadata:
      enabled: true
      priority: 0
      modules:
        - cookbook.servers.tools.read_file_tool
        - cookbook.servers.tools.glob_tool
        - cookbook.servers.tools.grep_tool

  # --- Memory ---
  - name: mymemory
    type: memory
    cls: cookbook.servers.memory.inmemory.InMemoryPlugin
    metadata:
      enabled: true
      working_limit: 50
      episodic_limit: 50
      semantic_limit: 50

  # --- Environment ---
  - name: counter_env
    type: env
    cls: cookbook.servers.counter_env.CounterEnv
    metadata:
      enabled: true

  # --- Processes ---
  - name: myprocs
    type: proc
    cls: a2e.caps.proc.plugin.ProcPlugin
    metadata:
      enabled: true
      priority: 5
      allowed_commands:
        - python3
        - bash
        - ls
      timeout: 30
      max_output_bytes: 1048576
      max_procs: 10
      network_disabled: true

  # --- Learning ---
  - name: mylearn
    type: learning
    cls: cookbook.servers.learn.learn.Learn
    metadata:
      enabled: true
      strategy: "ucb1"

  # --- Skills ---
  - name: filesystem_skill
    type: skill
    cls: cookbook.servers.skills.filesystem_skill.FilesystemSkillPlugin
    metadata:
      enabled: true

  # --- MCP ---
  - name: mymcp
    type: mcp
    cls: a2e.caps.mcp.plugin.MCPPlugin
    metadata:
      enabled: true
      priority: 10
      servers:
        - server_id: "local_tools"
          name: "Local Tools"
          transport: "stdio"
          cmd: ["python", "-m", "my_mcp_server"]
        - server_id: "remote_http"
          name: "Remote HTTP"
          transport: "sse"
          url: "http://localhost:8081/sse"
      routing_strategy: "auto"
      observability: true
```

## ServerConfig

| Field | Type | Default |
|-------|------|---------|
| `host` | `str` | `"0.0.0.0"` |
| `port` | `int` | `8765` |

## TransportConfig

| Field | Type | Description |
|-------|------|-------------|
| `type` | `str` | `"http"`, `"direct"`, or `"subprocess"` |
| `config` | `HTTPTransportConfig \| DirectTransportConfig \| SubprocessTransportConfig` | Type-specific config |

## AuditConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | — | Enable/disable audit |
| `path` | `str` | None | Log file path |
| `rotate` | `AuditRotateConfig` | — | Rotation settings |
| `session_id_source` | `str` | `"uuid"` | `"host_id"` or `"uuid"` |

## AuditRotateConfig

| Field | Type | Default |
|-------|------|---------|
| `max_bytes` | `int` | `10485760` (10 MB) |
| `backup_count` | `int` | `5` |

## SnapshotStoreConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `str` | `"file"` | `"file"`, `"sqlite"`, or `"custom"` |
| `config` | `dict` | `{}` | Type-specific config |
