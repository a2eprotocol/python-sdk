from typing import Any, Dict

from a2e.schema import (
    A2EHostConfig
)
from a2e.core.server.session import (
    Session
)
from a2e.core.transports import (
    DirectTransport,
)


class SessionManager:
    def __init__(
        self,
        config: A2EHostConfig,
        logger: Any
    ):
        self._sessions: Dict[str, Session] = {}
        self._logger = logger
        self._config = config

    def _create_transport(self):
        mode = self._config.transport.type

        if mode == "http":
            return DirectTransport(logger=self._logger)
        elif mode == "direct":
            return DirectTransport(logger=self._logger)
        else:
            raise ValueError(f"Unsupported transport: {mode}")

    def create(self) -> Session:
        transport = self._create_transport()
        s = Session(self._config, transport, self._logger)
        s.bind_transport()
        self._sessions[s.id] = s
        self._logger.info(f"[session] created {s.id}")
        return s

    def get(self, sid: str) -> Session:
        if sid not in self._sessions:
            raise KeyError(sid)
        return self._sessions[sid]

    def delete(self, sid: str):
        if sid in self._sessions:
            self._sessions[sid].server.stop()
            del self._sessions[sid]
            self._logger.info(f"[session] deleted {sid}")
