import os
import yaml
import logging
import uvicorn
from typing import Dict
import pdb

from a2e import A2EServer
from a2e.schema import A2EHostConfig


def create_app():
    logger = logging.getLogger(__name__)
    config_path = os.getenv("A2E_CONFIG", "config.yaml")
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    config = A2EHostConfig(**raw)

    server = A2EServer(
        config=config,
        logger=logger
    )

    app = server.start()
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )

if __name__ == "__main__":
    create_app()
