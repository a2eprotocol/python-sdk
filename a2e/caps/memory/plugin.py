import pdb
import time
from typing import Dict, Type, Optional
from pydantic import BaseModel

from a2e.caps.base import (
    A2EMessage,
    A2EError,
    A2EErrorCode
)
from a2e.core.plugins import (
    A2EPlugin
)

from a2e.caps.memory.protocol import (
    MemoryInitRequest,
    MemoryInitResponse,
    MemoryStoreRequest,
    MemoryStoreResponse,
    MemoryRetrieveRequest,
    MemoryRetrieveResponse,
    MemoryForgetRequest,
    MemoryForgetResponse,
    MessageType,
    MemoryEntry
)


class MemoryPlugin(A2EPlugin):
    def __init__(self, host_instance, config):
        super().setup(host_instance, config)

        # Memory ID --> Backend object
        self.memories = {}

    # -----------------------------------------------------
    # ABSTRACT HOOKS (child must implement)
    # -----------------------------------------------------
    def on_init(
        self,
        namespace: str,
        scope: dict,
        metadata: Optional[dict] = None,
    ):
        raise NotImplementedError

    def on_store(
        self,
        memory,
        entries: list[MemoryEntry]
    ) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    def on_retrieve(
        self,
        memory,
        req: MemoryRetrieveRequest
    ) -> list[MemoryEntry]:
        raise NotImplementedError

    def on_forget(
        self,
        memory,
        req: MemoryForgetRequest
    ) -> int:
        raise NotImplementedError

    # -----------------------------------------------------
    #  Protocol Messages
    # -----------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return {
            MessageType.MEMORY_INIT_REQ: MemoryInitRequest,
            MessageType.MEMORY_STORE_REQ: MemoryStoreRequest,
            MessageType.MEMORY_RETRIEVE_REQ: MemoryRetrieveRequest,
            MessageType.MEMORY_FORGET_REQ: MemoryForgetRequest,
        }

    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        response = None
        req_id = msg.id
        t0 = time.monotonic()
        t = msg.type

        # ─────────────────────────────
        # MEMORY_STORE_REQ
        # ─────────────────────────────
        if msg.type == MessageType.MEMORY_INIT_REQ:
            memory_id, memory_obj = self.on_init(
                namespace=msg.namespace,
                scope=msg.scope,
                metadata=msg.metadata,
            )

            self.memories[memory_id] = memory_obj
            response = MemoryInitResponse(
                req_id=req_id,
                memory_id=memory_id,
                namespace=msg.namespace,
            )
            self.audit_handle(
                msg,
                response,
                req_id,
                t0,
            )
            return response

        # =================================================
        # Resolve memory
        # =================================================
        try:
            memory = self.memories.get(msg.memory_id)
            if memory is None:
                return A2EError(
                    req_id=req_id,
                    code=A2EErrorCode.NOT_FOUND,
                    message=(
                        f"Memory not initialized: "
                        f"{msg.memory_id}"
                    ),
                    retryable=False,
                )
        except Exception as error:
            response = A2EError(
                req_id=req_id,
                code=A2EErrorCode.RUNTIME_ERROR,
                message=str(error),
                retryable=False,
            )
            return response

        if t == MessageType.MEMORY_STORE_REQ:
            try:
                memory_entries = [
                    MemoryEntry.model_validate(e)
                    for e in msg.entries
                ]

                stored, errors = self.on_store(
                    memory,
                    memory_entries
                )

                response = MemoryStoreResponse(
                    req_id=req_id,
                    stored=stored,
                    errors=errors,
                )
            except Exception as error:
                response = A2EError(
                    req_id=req_id,
                    code=A2EErrorCode.RUNTIME_ERROR,
                    message=str(error),
                    retryable=False,
                )
            finally:
                self.audit_handle(
                    msg,
                    response,
                    req_id,
                    t0,
                )
                return response

        # ─────────────────────────────
        # MEMORY_RETRIEVE_REQ
        # ─────────────────────────────
        if t == MessageType.MEMORY_RETRIEVE_REQ:
            try:
                results = self.on_retrieve(memory, msg)
                response = MemoryRetrieveResponse(
                    req_id=req_id,
                    entries=[
                        e.model_dump()
                        for e in results
                    ],
                    total=len(results),
                )
            except Exception as error:
                response = A2EError(
                    req_id=req_id,
                    code=A2EErrorCode.RUNTIME_ERROR,
                    message=str(error),
                    retryable=False,
                )
            finally:
                self.audit_handle(
                    msg,
                    response,
                    req_id,
                    t0,
                )
                return response

        # ─────────────────────────────
        # MEMORY_FORGET_REQ
        # ─────────────────────────────
        if t == MessageType.MEMORY_FORGET_REQ:
            try:
                deleted = self.on_forget(
                    memory,
                    msg
                )

                response = MemoryForgetResponse(
                    req_id=req_id,
                    deleted=deleted,
                )
            except Exception as error:
                response = A2EError(
                    req_id=req_id,
                    code=A2EError.RUNTIME_ERROR,
                    message=str(error),
                    retryable=False,
                )
            finally:
                self.audit_handle(
                    msg,
                    response,
                    req_id,
                    t0,
                )
                return response

        # ─────────────────────────────
        # Unsupported Message
        # ─────────────────────────────
        response = A2EError(
            req_id=req_id,
            code=A2EErrorCode.INVALID_MESSAGE,
            message=f"[memory] Unsupported message: {t}",
            retryable=False,
        )

        self.audit_handle(
            msg,
            response,
            req_id,
            t0,
        )
        return response
