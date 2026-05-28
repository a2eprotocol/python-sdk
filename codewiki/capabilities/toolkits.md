# Toolkits

```text
a2e/caps/toolkits/protocol.py — MessageType, ToolkitDefinition
a2e/caps/toolkits/plugin.py   — ToolkitPlugin ABC
a2e/caps/toolkits/client.py   — ToolkitAPI
```

## Overview

Toolkits are **bundled collections of tools** with shared configuration and schemas. While tools are individual operations, toolkits group related tools together and provide a configuration interface.

## Protocol Messages (4 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `toolkit/list/req` | `ToolkitListRequest` | Agent → Host |
| `toolkit/list/resp` | `ToolkitListResponse` | Host → Agent |
| `toolkit/configure/req` | `ToolkitConfigureRequest` | Agent → Host |
| `toolkit/configure/resp` | `ToolkitConfigureResponse` | Host → Agent |

### ToolkitDefinition

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique toolkit name |
| `alias` | `str` | Display alias |
| `description` | `str` | What the toolkit provides |
| `category` | `str` | Classification |
| `tags` | `list[str]` | Search tags |
| `icon_svg` | `str` | SVG icon |
| `schema` | `dict` | Configuration JSON Schema |
| `tools` | `list[str]` | Tool names included |
| `configured` | `bool` | Whether toolkit is configured |
| `version` | `str` | Toolkit version |

### ToolkitConfigureRequest

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Session identifier |
| `toolkit_name` | `str` | Toolkit to configure |
| `config` | `dict` | Configuration values matching schema |

### ToolkitConfigureResponse

| Field | Type | Description |
|-------|------|-------------|
| `toolkit_name` | `str` | Configured toolkit name |
| `status` | `str` | Configuration result status |
| `message` | `str` | Human-readable message |

## ToolkitPlugin ABC

```python
class ToolkitPlugin(A2EPlugin):
    name = "toolkit_plugin"

    @abstractmethod
    def _list_toolkits(self, msg) -> list[ToolkitDefinition]: ...

    @abstractmethod
    def _configure_toolkit(self, msg) -> ToolkitConfigureResponse: ...

    # Push support
    def set_push_callback(self, cb): ...
    def emit_event(self, ...): ...
```

## ToolkitAPI (Client)

```python
from a2e.caps.toolkits.client import ToolkitAPI

toolkits = ToolkitAPI(client)

# List available toolkits
kit_list = toolkits.list(filter_kind=None, filter_tags=None)

# Configure a toolkit
kit = toolkits.configure("filesystem", schema={"root": "/data"})

# Idempotent: configure only if not already configured
kit = toolkits.ensure("filesystem", schema={"root": "/data"})

# Find by name
kit = toolkits.get("filesystem")  # Returns ToolkitDefinition or None
```

### Convenience Methods

| Method | Description |
|--------|-------------|
| `ensure(name, schema, timeout)` | Idempotent configure — checks if already configured first |
| `get(name, timeout)` | Find toolkit by name from list |
