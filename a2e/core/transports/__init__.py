import pdb
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Union, Literal
from a2e.core.transports.http import (
    HTTPTransport
)
from a2e.core.transports.direct import (
    DirectTransport
)


# ─────────────────────────────────────────────
# HTTP Transport Config
# ─────────────────────────────────────────────
class HTTPTransportConfig(BaseModel):
    base_url: HttpUrl = Field(
        ...,
        description="Base URL of A2E server"
    )
    send_path: str = Field(
        "/send",
        description="POST endpoint for sending messages"
    )
    stream_path: str = Field(
        "/stream",
        description="SSE endpoint for receiving messages"
    )


# ─────────────────────────────────────────────
# Direct Transport Config (placeholder)
# ─────────────────────────────────────────────
class DirectTransportConfig(BaseModel):
    # no config needed for now
    pass


# ─────────────────────────────────────────────
# Subprocess Transport Config (placeholder)
# ─────────────────────────────────────────────
class SubprocessTransportConfig(BaseModel):
    command: Optional[str] = Field(
        None,
        description="Command to launch subprocess"
    )


# ─────────────────────────────────────────────
# Transport Wrapper
# ─────────────────────────────────────────────
class TransportConfig(BaseModel):
    type: Literal["http", "direct", "subprocess"]
    config: Union[
        HTTPTransportConfig,
        DirectTransportConfig,
        SubprocessTransportConfig,
    ]


def build_transport(cfg: TransportConfig, logger):
    ttype = cfg.type
    tconf = cfg.config or {}

    if ttype == "http":
        return HTTPTransport(
            base_url=tconf.base_url,
            logger=logger,
            send_path=tconf.send_path,
            stream_path=tconf.stream_path,
        )
    elif ttype == "direct":
        raise ValueError("DirectTransport must be injected programmatically")
    else:
        raise ValueError(f"Unknown transport type: {ttype}")


__all__ = [
    "build_transport",
    "TransportConfig",
    "HTTPTransport",
    "DirectTransport",
    "HTTPTransportConfig"
]
