"""
cookbook/servers/a2e_subprocess_host.py — A2E Host via SubprocessTransport

Runs the A2E host session as an stdin/stdout subprocess.
The host reads NDJSON from stdin and writes NDJSON to stdout.

This is useful for:
  - Running the host as a child process inside an agent
  - Docker sidecar pattern (host in one container, agent in another)
  - Testing with real process boundaries

Start:
    python cookbook/servers/a2e_subprocess_host.py --config config.yaml

The host will print a startup banner and wait for NDJSON on stdin.
"""
from __future__ import annotations

import json
import logging
import sys
import threading

from a2e.core.transports.direct import DirectTransport
from a2e.core.server.executor import A2EServerRuntimeExecutor
from a2e.schema import A2EHostConfig


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("subprocess-host")


def main():
    import argparse
    import yaml

    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True, help="Path to A2E host config YAML")
    args = p.parse_args()

    with open(args.config) as f:
        raw = yaml.safe_load(f)

    config = A2EHostConfig(**raw)

    # ─────────────────────────────────────────────
    # Build the host side of the transport pair
    # The SubprocessTransport will be used by the
    # external caller (agent) — the host uses a
    # DirectTransport wired to it.
    # ─────────────────────────────────────────────

    # Agent-side: stdin/stdout transport
    # Host-side: DirectTransport wired to agent
    agent_transport_host = DirectTransport(logger=logger)

    host_runtime = A2EServerRuntimeExecutor(
        config=config,
        transport=agent_transport_host,
        logger=logger,
    )

    host_runtime.start()

    # Print startup banner so the agent knows we're ready
    print("A2E_SUBPROCESS_HOST_READY", flush=True)

    logger.info("Subprocess host started, reading stdin...")

    # Read NDJSON from stdin and inject into host transport
    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            # Inject into the host's transport
            # Use deliver() since we're the external caller
            import asyncio
            asyncio.run(agent_transport_host.deliver(line))

    except EOFError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        host_runtime.stop()
        logger.info("Subprocess host stopped")


if __name__ == "__main__":
    main()
