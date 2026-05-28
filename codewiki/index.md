---
layout: home
hero:
  name: "A2E Protocol"
  text: "Agent-to-Environment"
  tagline: "A protocol and Python SDK for building stateful, interactive environments for LLM agents"
  actions:
    - theme: brand
      text: Getting Started
      link: /getting-started/quickstart
    - theme: alt
      text: Architecture
      link: /architecture/overview
    - theme: alt
      text: Protocol Spec
      link: /protocol-spec/message-format
features:
  - icon: 🔌
    title: Plugin-Based Runtime
    details: "Thin execution kernel with all capabilities as dynamically loaded plugins. 9 built-in capability namespaces: tools, memory, env, proc, learn, skills, toolkits, chains, mcp."
  - icon: ⚡
    title: "9 Capability Namespaces"
    details: "Tools, Memory (3-tier), RL Environments, Process management, Learning/feedback, Skills, Toolkits, Chain pipelines, MCP bridge — negotiated at handshake."
  - icon: 🔄
    title: "Stateful Sessions + Persistence"
    details: "Session-per-connection with snapshot/restore, pluggable storage (file or SQLite), and structured audit logging with rotation."
---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Protocol | NDJSON over Pydantic v2 |
| Server | FastAPI + Uvicorn |
| Transport | HTTP+SSE / In-process Direct |
| Schema | Pydantic BaseModel (validation + serialization) |
| Persistence | File / SQLite |

## Quick Navigation

- [Quick Start Guide](/getting-started/quickstart)
- [Architecture Overview](/architecture/overview)
- [Client API Reference](/sdk-reference/client-api)
- [Protocol Specification](/protocol-spec/message-format)
- [Capabilities Index](/capabilities/tools)
