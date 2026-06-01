"""
cookbook/agents/subprocess_agent.py — A2E Agent over SubprocessTransport

Connects to an A2E host running as a subprocess. The agent
launches the host as a child process and communicates over
its stdin/stdout pipes.

This is the simplest production setup:
  - Agent and host are separate processes
  - Communication over line-delimited NDJSON via pipes
  - No network, no HTTP server, no port configuration

Usage:
    python cookbook/agents/subprocess_agent.py

The script launches:
  1. An A2E host as a subprocess (via SubprocessTransport)
  2. An A2E agent that connects to it
  3. Runs a ping test to verify connectivity
"""
from __future__ import annotations

import logging
import sys
import time

from a2e.core.transports.subprocess import SubprocessTransport
from a2e.core.client.client import A2EClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("subprocess-agent")


class SubprocessAgent:
    """
    A2E agent that runs the host as a subprocess.

    The host command is a Python script that creates an A2E runtime
    and reads NDJSON from stdin. This agent launches it, connects,
    and exposes the standard A2E client interface.
    """

    def __init__(
        self,
        host_command: list[str],
        agent_id: str = "subprocess-agent",
    ):
        self._transport = SubprocessTransport(
            command=host_command,
            logger=logger,
        )
        self._client = A2EClient(
            transport=self._transport,
            logger=logger,
            agent_id=agent_id,
            agent_caps=[],
        )

    def start(self):
        self._transport.start()
        self._client.connect()
        logger.info(
            "Connected session=%s",
            self._client._session_id,
        )

    def stop(self):
        self._client.disconnect()
        self._transport.stop()

    def ping(self) -> float:
        ms = self._client.ping()
        logger.info("ping=%.2f ms", ms)
        return ms

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


def main():
    """
    Launches a simple echo host as a subprocess.
    The echo host reads NDJSON from stdin and writes it back.
    """
    echo_host_script = """
import sys, json, traceback
from a2e.core.transports.direct import DirectTransport
from a2e.core.server.executor import A2EServerRuntimeExecutor
from unittest.mock import MagicMock

# Minimal config (no plugins)
config = MagicMock()
config.plugins = []
config.audit.enabled = False
config.transport.type = "direct"

host_transport = DirectTransport(logger=type('L',(),{
    'info': lambda *a: None, 'warning': lambda *a: None,
    'debug': lambda *a: None, 'exception': lambda *a: None,
})())
executor = A2EServerRuntimeExecutor(config, host_transport, type('L',(),{
    'info': lambda *a: None, 'warning': lambda *a: None,
    'debug': lambda *a: None, 'exception': lambda *a: None,
})())
executor.start()
print("A2E_HOST_READY", flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    host_transport.deliver(line)
"""

    import shlex
    host_cmd = [sys.executable, "-c", echo_host_script]

    agent = SubprocessAgent(host_command=host_cmd)
    agent.start()
    agent.ping()
    agent.stop()
    logger.info("Done")


if __name__ == "__main__":
    main()
