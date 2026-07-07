"""
Standalone A2E planning server — demonstrates the planning capability.
"""
import logging
import time
from a2e.core.transports import build_transport
from a2e.schema import A2EHostConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main(config_path: str | None = None):
    import yaml

    config = _load_config(config_path)
    transport = build_transport(config.transport, logger)

    from a2e.server import A2EServer

    server = A2EServer(config=config, transport=transport, logger=logger)

    try:
        server.start()
        logger.info("Planning server running on %s:%s",
                     config.server.host, config.server.port)
        while transport.alive():
            time.sleep(0.5)
    finally:
        server.stop()


def _load_config(path: str | None = None) -> A2EHostConfig:
    import os
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(path) as f:
        raw = yaml.safe_load(f)
    return A2EHostConfig(**raw)


if __name__ == "__main__":
    main()