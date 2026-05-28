"""
http_env_client.py
──────────────────
HttpEnvClient _ speaks the standard HTTP protocol to a running
environment container.

This replaces BaseEnv for the Docker-backed architecture.
Instead of calling Python methods on a local object, it sends
HTTP requests to a container that implements the env contract.

Standard container HTTP API (must be implemented by every env image):

  POST /reset
    Request: {"episode_id": str, "task_config": {}}
    Response: {"observation": Observation, "info": {}}

  POST /step
    Request: {"episode_id": str, "action": str}
    Response: {"observation": Observation, "reward": float,
               "done": bool, "truncated": bool, "info": {}}

  POST /close
    Request: {"episode_id": str}
    Response: {"status": "ok"}

  GET /healthz
    Response: {"status": "ok"}

All responses are parsed into the same StepResult type used throughout
the pipeline, so the rest of the cluster code is unchanged.
"""

import pdb
import logging
import sys
import argparse
from typing import Literal

from a2e.core.transports import (
    build_transport,
    TransportConfig,
    HTTPTransportConfig
)
from a2e.caps.base.protocol import (
    A2ECapability,
)
from a2e.client import A2EClient
from env_api import run_env
from proc_api import run_proc
from mem_api import run_mem
from tool_api import run_tool
from toolkit_api import run_toolkit
from skill_api import run_skill
from mcp_api import run_mcp


# ─────────────────────────────────────────────
# Optional: sleep to observe async pushes
# ─────────────────────────────────────────────
CapabilityType = Literal["memory", "toolkit", "tool", "proc", "env", "skills", "mcp"]

# ─────────────────────────────────────────────────────────────
# Logger setup
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("a2e-client")


def dispatch(client, capability: CapabilityType):
    if capability == "memory":
        run_mem(client)
    elif capability == "toolkit":
        run_toolkit(client)
    elif capability == "tool":
        run_tool(client)
    elif capability == "proc":
        run_proc(client)
    elif capability == "env":
        run_env(client)
    elif capability == "skills":
        run_skill(client)
    elif capability == "mcp":
        run_mcp(client)
    else:
        raise ValueError(f"Unsupported capability: {capability}")


# ─────────────────────────────────────────────────────────────
# Main client flow
# ─────────────────────────────────────────────────────────────
def main(capability: CapabilityType):
    # Example: host process (could be your A2E server)
    #transport = SubprocessTransport(
    #    cmd=["python3", "-m", "a2e.server", "--config", "config.yaml"],
    #    logger=logger
    #)
    transport_config = TransportConfig(**{
        "type": "http",
        "config": HTTPTransportConfig(**{
            "base_url": "http://localhost:8765",
            "stream": "/stream",
            "send": "/send"
        })
    })

    transport = build_transport(transport_config, logger)
    client = A2EClient(
        transport=transport,
        logger=logger,
        agent_id="agent-analytics-01",
        auth_token="",  # dev mode
        agent_caps=[
            A2ECapability.TOOLKITS,
            A2ECapability.ENV,
            A2ECapability.PROC
        ],
    )

    try:
        # ─────────────────────────────────────────────
        # Connect + Handshake
        # ─────────────────────────────────────────────
        client.connect()
        logger.info(f"Session established: {client._session_id}")
        logger.info(f"Accepted capabilities: {client._accepted_caps}")

        # ─────────────────────────────────────────────
        # Ping (health check)
        # ─────────────────────────────────────────────
        latency = client.ping()
        logger.info(f"Ping latency: {latency:.2f} ms")

        dispatch(client, capability)
    except TimeoutError as e:
        logger.error(f"Timeout: {e}")
    except ConnectionError as e:
        logger.error(f"Handshake failed: {e}")
    except Exception as e:
        logger.error(
            f"A2E Error | code={e.code} | message={e.message} | retryable={e.retryable}"
        )

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")

    finally:
        # ─────────────────────────────────────────────
        # Graceful shutdown
        # ─────────────────────────────────────────────
        logger.info("[client] Shutting down...")
        client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run capability selector")
    parser.add_argument(
        "--capability",
        type=str,
        required=True,
        choices=["memory", "toolkit", "tool", "proc", "env", "skills", "mcp"],
        help="Capability to execute"
   )

    args = parser.parse_args()
    main(args.capability)
