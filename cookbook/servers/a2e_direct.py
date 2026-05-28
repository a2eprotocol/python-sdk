import logging
import yaml
import os

from a2e.core.transports.direct import DirectTransport
from a2e.server import A2EServer
from a2e.schema import A2EHostConfig
from a2e.client import A2EClient
from a2e.core.transports import (
    build_transport,
    TransportConfig
)


def create_server(transport):
    logger = logging.getLogger(__name__)

    # ─────────────────────────────────────────────
    # Load config
    # ─────────────────────────────────────────────
    config_path = os.getenv("A2E_CONFIG", "config.yaml")
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    config = A2EHostConfig(**raw)

    # ─────────────────────────────────────────────
    # Create transports (2 ends)
    # ─────────────────────────────────────────────
    t1 = DirectTransport(logger=logger)
    
    # ─────────────────────────────────────────────
    # Create runtimes
    # ─────────────────────────────────────────────
    r1 = A2EServer(
        config=config,
        transport=t1,
        logger=logger,
    )
    r1.start()
    return r1

def create_client(transport):
    logger = logging.getLogger(__name__)

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
    return client


def main():
    logger = logging.getLogger(__name__)

    # create BOTH transports
    t_server = DirectTransport(logger=logger)
    t_client = DirectTransport(logger=logger)

    # 🔥 CRITICAL: connect them
    t_server.connect(t_client)

    # create server + client with SAME pair
    server = create_server(t_server)
    client = create_client(t_client)

    try:
        client.connect()

        logger.info(f"Session: {client._session_id}")

        latency = client.ping()
        logger.info(f"Ping: {latency:.2f} ms")

    finally:
        client.disconnect()
        server.stop()

if __name__ == '__main__':
    main()
