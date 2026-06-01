import pdb
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Union, Literal
from a2e.core.transports.http import (
    HTTPTransport
)
from a2e.core.transports.direct import (
    DirectTransport
)
from a2e.core.transports.subprocess import (
    SubprocessTransport
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
        description="Command to launch subprocess (e.g. 'python3 -c \"...\"')"
    )
    env: Optional[dict[str, str]] = Field(
        None,
        description="Environment variables to pass to subprocess"
    )
    cwd: Optional[str] = Field(
        None,
        description="Working directory for subprocess"
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
    elif ttype == "subprocess" or ttype == "stdio":
        if not tconf.command:
            raise ValueError("SubprocessTransport requires a 'command' in config")

        import shlex
        cmd = tconf.command if isinstance(tconf.command, list) else shlex.split(tconf.command)
        return SubprocessTransport(
            command=cmd,
            logger=logger,
            env=getattr(tconf, "env", None),
            cwd=getattr(tconf, "cwd", None),
        )
    else:
        raise ValueError(f"Unknown transport type: {ttype}")


__all__ = [
    "build_transport",
    "TransportConfig",
    "HTTPTransport",
    "DirectTransport",
    "SubprocessTransport",
    "HTTPTransportConfig",
    "DirectTransportConfig",
    "SubprocessTransportConfig",
]
