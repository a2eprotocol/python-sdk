import pdb
from typing import Any
from a2e.core.client import A2EClient
from a2e.caps.memory import (
    MemoryInitRequest,
    MemoryInitResponse,
    MemoryStoreRequest,
    MemoryStoreResponse,
    MemoryRetrieveRequest,
    MemoryRetrieveResponse,
    MemoryForgetRequest,
    MemoryForgetResponse,
    MemoryTier,
    MemoryEntry,
    MEMORY_TYPE_MAP
)


class MemoryAPI:
    def __init__(self, client: A2EClient):
        self._c = client
        self.memory_id = None
        self._c.update_msg_types(MEMORY_TYPE_MAP)

    def init(self, namespace: str = "default", scope: dict | None = None, metadata: dict | None = None):
        req = MemoryInitRequest(
            namespace=namespace,
            scope=scope or {},
            metadata=metadata or {},
        )

        resp = self._c.rpc(req)
        if not isinstance(resp, MemoryInitResponse):
            raise ConnectionError(
                f"Unexpected init response: "
                f"{type(resp)}"
            )

        self.memory_id = resp.memory_id
        return resp

    def _ensure_initialized(self):
        if self.memory_id is None:
            self.init()

    def store(
        self,
        entries: list[MemoryEntry] | list[dict],
        timeout: int = 10,
    ) -> tuple[list[str], list[str]]:

        self._ensure_initialized()

        raw = [e if isinstance(e, dict) else e.__dict__ for e in entries]
        req = MemoryStoreRequest(
            memory_id=self.memory_id,
            entries=raw
        )
        resp = self._c.rpc(req, timeout=timeout)

        if not isinstance(resp, MemoryStoreResponse):
            raise ConnectionError(
                f"Unexpected memory store response: {type(resp)}"
            )
        return resp.stored, resp.errors

    def retrieve(
        self,
        keys: list[str] = None,
        query: str = "",
        tags: list[str] = None,
        tier: str = "",
        limit: int = 10,
        min_score: float = 0.0,
        timeout: int = 10,
    ) -> list[MemoryEntry]:
        self._ensure_initialized()

        req = MemoryRetrieveRequest(
            memory_id=self.memory_id,
            keys=keys or [],
            query=query,
            tags=tags or [],
            tier=tier,
            limit=limit,
            min_score=min_score,
        )
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, MemoryRetrieveResponse):
            raise ConnectionError(f"Unexpected memory retrieve response: {type(resp)}")
        return [MemoryEntry.model_validate(e) for e in resp.entries]

    def forget(
        self,
        keys: list[str] = None,
        tags: list[str] = None,
        tier: str = MemoryTier.EPISODIC.value,
        timeout: int = 10,
    ) -> int:
        self._ensure_initialized()

        req = MemoryForgetRequest(
            memory_id=self.memory_id,
            keys=keys or [],
            tags=tags or [],
            tier=tier
        )
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, MemoryForgetResponse):
            raise ConnectionError(f"Unexpected memory forget response: {type(resp)}")
        return resp.deleted

    def remember(
        self,
        key: str,
        value: Any,
        tier: str,
        tags: list[str] = None,
        ttl: int = 0,
        score: float = 1.0
    ):
        """Convenience: store a single key-value pair."""
        entry = MemoryEntry(
            key=key,
            content=value,
            tier=tier,
            tags=tags or [],
            ttl=ttl,
            score=score
        )
        return self.store([entry])

    def recall(self, key: str, default: Any = None) -> Any:
        """Convenience: retrieve a single key."""

        entries = self.retrieve(keys=[key])
        return entries[0].content if entries else default
