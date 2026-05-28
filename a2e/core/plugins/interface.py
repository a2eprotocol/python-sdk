import pdb
import uuid
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional, Type
from pydantic import BaseModel
from a2e.core.store.base import (
    SnapshotStore
)
from a2e.caps.base.protocol import (
    A2EMessage,
    A2EError
)
from a2e.core.audit import (
    AuditEntry,
    AuditLog
)


class A2EPlugin(ABC):
    name: str
    type: str
    priority: int = 0
    exclusive: bool = False

    def setup(
        self,
        host_instance,
        config: dict
    ):
        self.host_instance = host_instance
        self.config = config or {}

        # For audit logging
        self._audit: Optional[AuditLog] = config.get("audit_log")
        self._session_id: str = config.get("session_id", str(uuid.uuid4()))

    @abstractmethod
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        pass

    @abstractmethod
    def handle(self, message: BaseModel):
        pass

    def caps_metadata(self):
        return {
            "name": self.name,
            "type": self.config['type'],
            "priority": self.config['priority'],
            "exclusive": self.config['exclusive']
        }

    # ─────────────────────────────────────────────
    # 🔥 State Management APIs
    # ─────────────────────────────────────────────
    def clear_state(
        self,
        store: "SnapshotStore", key: str,
        session_id: Optional[str] = None
    ):
        """
        Clear plugin state.
        If session_id is None → clear ALL state
        Else → clear only session-scoped state
        """
        pass

    def save_state(
        self,
        store: "SnapshotStore", key: str,
        session_id: Optional[str] = None
    ):
        """
        Save state using provided store.
        """
        state = self.snapshot_state(session_id)
        store.save(f"{self.name}:{key}", state)

    def restore_state(
        self,
        store: "SnapshotStore", key: str,
        session_id: Optional[str] = None
    ):
        """
        Restore state from snapshot
        """
        state = self.snapshot_state(session_id)
        store.load(f"{self.name}:{key}", state)

    def teardown(self):
        pass

    # -----------------------------------------------------------------------
    # Audit helper
    # -----------------------------------------------------------------------
    def audit_handle(
        self,
        msg: A2EMessage,
        response: A2EMessage | None,
        req_id: str,
        t0: float,
    ) -> None:
        """Record one AuditEntry for the completed handle() call."""
        if not self._audit:
            return

        is_error = isinstance(response, A2EError)
        error_code: str | None = str(response.code) if is_error else None

        # Best-effort byte sizing — avoids hard crash if serialisation fails
        try:
            input_bytes = len(msg.model_dump_json().encode())
        except Exception:
            input_bytes = 0
        try:
            output_bytes = len(response.model_dump_json().encode()) if response else 0
        except Exception:
            output_bytes = 0

        entry = AuditEntry(
            ts=time.time(),
            session_id=self._session_id,
            req_id=req_id,
            correlation_id=req_id,
            success=not is_error,
            duration_ms=int((time.monotonic() - t0) * 1000),
            error_code=error_code,
            input_bytes=input_bytes,
            output_bytes=output_bytes,
        )
        try:
            self._audit.record(entry)
        except Exception as exc:
            # Audit must never crash the plugin
            print(f"[Plugin] audit record failed: {exc}")
