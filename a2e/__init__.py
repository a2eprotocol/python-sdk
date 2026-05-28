"""
A2E — Agent-to-Environment Protocol

Overview
────────
A2E defines a standard interface between an agent and its execution or
training environment. It builds on ideas from MCP (Model Context Protocol)
and A2A (Agent-to-Agent), recognizing that agent runtime and training
environments share common primitives with only incremental differences.

As agent systems evolve toward more complex, stateful, and long-running
interactions, A2E provides a unified protocol to:
  • standardize environment interaction
  • enable portability across runtimes and simulators
  • reduce bespoke integrations
  • support both inference-time and training-time workflows

Design Principles
─────────────────
  • Composability: small, orthogonal namespaces
  • Backward compatibility with SCP 1.0
  • Transport-agnostic, NDJSON-based messaging
  • Explicit separation of tools, environment, memory, and learning

Namespaces
──────────
  skill/*        — core skills
  toolkit/*    — Grouped environment toolkits (e.g., shellToolkit, fsToolkit)
  tool/*       — primitive tools (e.g., shell, fs, http)
  mcp/*        - MCP gateway
  env/*        — environment observation and control
  skills/*     - skills for agents
  proc/*       — long-running process lifecycle management
  memory/*     — episodic and semantic memory interfaces
  learn/*      — feedback signals, experience replay, performance tracking
  chain/*      — multi-step tool/skill composition and execution

Wire Format
───────────
Messages are newline-delimited JSON (NDJSON), identical to SCP:

  { "a2e": "1.0", "id": "<uuid>", "type": "<namespace/verb>", ... }

Compatibility
─────────────
A2E is a strict superset of SCP 1.0.

Hosts that only support SCP will ignore unknown namespaces and may return
`error/unknown_type`. Clients are expected to detect this and gracefully
downgrade to SCP-compatible interactions when required.

Quick start
───────────
    import logging
    from a2e.caps.base.protocol import (
        A2ECapability,
    )
    from a2e.client import A2EClient
    from a2e.core.transports import (
        build_transport,
        TransportConfig,
        HTTPTransportConfig,
    )

    logger = logging.getLogger('a2e')
    transport_config = TransportConfig(**{
        "type": "http",

        "config": HTTPTransportConfig(**{
            "base_url": "http://localhost:8765",
            "stream": "/stream",
            "send": "/send",
        }),
    })

    transport = build_transport(
        transport_config,
        logger,
    )

    client = A2EClient(
        transport=transport,
        logger=logger,
        agent_id="thirdparty-http-agent",
        auth_token="",
        agent_caps=[
            A2ECapability.TOOLKITS,
            A2ECapability.ENV,
            A2ECapability.PROC,
        ],
    )

    client.discover()
    client.tools.list_tools()

    result = client.call("text_summarizer", {"text": "Hello world"})
    tr = client.tools.shell("echo hello")
    snap = client.env.observe()

    client.memory.remember("last_result", result.output)
    client.learn.reward("text_summarizer", 1.0)

    Protocol version: 1.0
"""
from a2e.core.server import A2EServer
from a2e.core.client import A2EClient


__all__ = [
    "A2EClient",
    "A2EServer",
]


