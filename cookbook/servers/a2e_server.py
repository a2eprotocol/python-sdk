import logging
from a2e.schema import (
    A2EHostConfig
)
from a2e.server import (
    A2EServer
)
from a2e.core.transports import (
    build_transport
)

def main():
    import argparse
    import yaml
    import logging
    import time

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    args = p.parse_args()

    # ─────────────────────────────────────────────
    # Load config
    # ─────────────────────────────────────────────
    with open(args.config) as f:
        raw_cfg = yaml.safe_load(f)

    config = A2EHostConfig(**raw_cfg)

    # ─────────────────────────────────────────────
    # Build transport
    # ─────────────────────────────────────────────
    transport = build_transport(config.transport, logger)

    # ─────────────────────────────────────────────
    # Start server
    # ─────────────────────────────────────────────
    server = A2EServer(
        config=config,
        transport=transport,
        logger=logger,
    )

    try:
        server.start()

        while transport.alive():
            time.sleep(0.5)

    finally:
        server.stop()


if __name__ == "__main__":
    main()
