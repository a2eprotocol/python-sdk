"""
cookbook/agents/direct_agent.py — A2E Agent over DirectTransport

Demonstrates connecting an agent to a host using an in-memory
DirectTransport pair. No network, no subprocess — both sides
run in the same process via wired queue pairs.

Usage:
    # Terminal 1: start host
    python cookbook/servers/a2e_direct.py

    # Terminal 2 (or same process): run this agent
    python cookbook/agents/direct_agent.py

Or both in one script:
    python cookbook/agents/direct_agent.py --self-contained

This is the fastest path for:
  - Testing agent logic without network
  - RL training loops (thousands of steps/second)
  - Embedded agent + host deployments
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Optional

from a2e.core.transports.direct import DirectTransport
from a2e.core.client.client import A2EClient
from a2e.core.transports import build_transport, TransportConfig
from a2e.caps.base.protocol import (
    A2EMessage,
    A2ECapability,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("direct-agent")


class DirectAgent:
    """Minimal A2E agent over a DirectTransport pair."""

    def __init__(
        self,
        client_transport: DirectTransport,
        agent_id: str = "direct-agent",
        caps: Optional[list[str]] = None,
    ):
        self._client = A2EClient(
            transport=client_transport,
            logger=logger,
            agent_id=agent_id,
            agent_caps=caps or [A2ECapability.TOOLS, A2ECapability.ENV],
        )

    def start(self):
        self._client.connect()
        logger.info(
            "session=%s caps=%s",
            self._client._session_id,
            [c.capability for c in self._client.capabilities()],
        )

    def stop(self):
        self._client.disconnect()

    def ping(self) -> float:
        ms = self._client.ping()
        logger.info("ping=%.2f ms", ms)
        return ms

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


def standalone():
    """Create both host and agent in the same process."""
    from a2e.core.server.executor import A2EServerRuntimeExecutor
    from a2e.schema import A2EHostConfig
    import yaml

    # Load config
    with open("cookbook/servers/config.yaml") as f:
        raw = yaml.safe_load(f)

    raw["transport"] = {"type": "direct", "config": {}}
    config = A2EHostConfig(**raw)

    # Create wired transport pair
    server_transport = DirectTransport(logger=logger)
    client_transport = DirectTransport(logger=logger)
    server_transport.connect(client_transport)
    client_transport.connect(server_transport)

    # Start host runtime
    executor = A2EServerRuntimeExecutor(
        config=config, transport=server_transport, logger=logger
    )
    executor.start()

    # Connect agent
    agent = DirectAgent(client_transport)
    agent.start()

    logger.info("Self-contained mode: host + agent running")
    logger.info("Session: %s", agent._client._session_id)

    # Verify connectivity
    agent.ping()

    # Cleanup
    agent.stop()
    executor.stop()


if __name__ == "__main__":
    if "--self-contained" in sys.argv:
        standalone()
    else:
        # Connect to a separately running host
        import argparse

        p = argparse.ArgumentParser()
        p.add_argument("--agent-id", default="direct-agent")
        args = p.parse_args()

        # Create client-side transport (server must provide the other half)
        client_transport = DirectTransport(logger=logger)

        agent = DirectAgent(client_transport, agent_id=args.agent_id)
        agent.start()
        agent.ping()
        agent.stop()
