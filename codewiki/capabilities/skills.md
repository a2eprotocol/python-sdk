# Skills

```text
a2e/caps/skills/protocol.py — MessageType, SkillDefinition, SkillResult
a2e/caps/skills/plugin.py   — SkillPlugin ABC
a2e/caps/skills/client.py   — SkillAPI
```

## Overview

Skills are **higher-level, sandboxed execution units** compared to tools. While tools are primitive operations, skills can be multi-step procedures with LLM integration, custom instructions, and streaming execution events.

## Protocol Messages (5 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `skill/discover/req` | `SkillDiscoverRequest` | Agent → Host |
| `skill/discover/resp` | `SkillDiscoverResponse` | Host → Agent |
| `skill/call/req` | `SkillCallRequest` | Agent → Host |
| `skill/call/resp` | `SkillCallResponse` | Host → Agent |
| `skill/event` | `SkillEvent` | Host → Agent (streaming) |

### SkillDefinition

Comprehensive skill manifest:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique skill name |
| `version` | `str` | Skill version |
| `description` | `str` | What the skill does |
| `triggers` | `list[str]` | When to activate this skill |
| `tools` | `list[str]` | Required tools |
| `toolkits` | `list[str]` | Required toolkits |
| `status` | `SkillStatus` | `Created`, `Blocked`, `Published`, `Archived` |
| `input_schema` | `dict` | JSON Schema for input |
| `output_schema` | `dict` | JSON Schema for output |
| `instructions` | `str` | LLM instructions/prompt |
| `file_path` | `str` | Skill file location |
| `llm_config` | `LLMConfig` | LLM provider settings |
| `arguments` | `dict` | Default arguments |
| `when_to_use` | `str` | Usage hint |
| `argument_hint` | `str` | Argument guidance |
| `source` | `str` | Origin |
| `category` | `str` | Skill category |
| `tags` | `list[str]` | Search tags |
| `max_turns` | `int` | Max execution turns |
| `timeout_seconds` | `float` | Execution timeout |
| `icon` | `str` | Display icon |
| `metadata` | `dict` | Extra metadata |

### SkillResult

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Execution succeeded |
| `data` | `dict` | Result data |
| `summary` | `str` | Human-readable summary |
| `truncated` | `bool` | Output truncated |
| `error` | `str` | Error message |
| `error_code` | `SkillErrorCode` | `UNKNOWN_SKILL`, `SKILL_ERROR`, `RUNTIME_ERROR` |
| `duration_ms` | `int` | Execution time |
| `events` | `list[SkillEvent]` | Streaming events collected |

### SkillEvent (extends A2EEvent)

Streaming events during skill execution with kinds: `skill.started`, `tool.started`, `tool.completed`, `tool.failed`, `llm.started`, `llm.token`, `llm.completed`, `skill.completed`, `skill.failed`.

### LLMConfig

| Field | Type | Description |
|-------|------|-------------|
| `provider_name` | `str` | LLM provider (e.g. `"anthropic"`) |
| `provider_credentials` | `dict` | API keys |
| `provider_config` | `dict` | Provider-specific settings |
| `is_default` | `bool` | Use as default LLM |

## SkillPlugin ABC

```python
class SkillPlugin(A2EPlugin):
    @abstractmethod
    def _list_skills(self) -> list[SkillDefinition]: ...

    @abstractmethod
    def _execute_skill(self, name, arguments, context) -> SkillResult: ...

    def discover(self, msg):
        # List skills then filter by tags and categories

    def call(self, msg):
        # Execute skill with streaming support
        # Creates inner emit_event() closure
        # Passes context dict: {emit_event, llm_override, metadata, streaming}
```

## SkillAPI (Client)

```python
from a2e.caps.skills.client import SkillAPI

skills = SkillAPI(client)

# Discover available skills
skill_list = skills.discover(tags=["analysis"], categories=["data"])

# Call a skill
result = skills.call(
    name="example-analysis",
    arguments={"data": "sample"},
    streaming=True,
    on_event=lambda event: print(f"Event: {event.kind}"),
    timeout=60.0
)

if result.success:
    print(result.data)
```
