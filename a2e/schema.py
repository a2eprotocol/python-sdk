import uuid
from pydantic import BaseModel, Field
from typing import Any, Optional, List, Dict, Literal
from pathlib import Path

from a2e.core.plugins import PluginConfig
from a2e.core.store import SnapshotStoreConfig
from a2e.core.transports import (
    TransportConfig
)


class ServerConfig(BaseModel):
    host: Optional[str] = "0.0.0.0"
    port: Optional[int] = 8765


# ── Audit schema ─────────────────────────────────────────────────────────────

class AuditRotateConfig(BaseModel):
    max_bytes: int = 10 * 1024 * 1024   # 10 MB
    backup_count: int = 5


class AuditConfig(BaseModel):
    enabled: bool = False
    path: Optional[str] = None          # None → logger-only, no file
    rotate: AuditRotateConfig = Field(default_factory=AuditRotateConfig)
    session_id_source: Literal["host_id", "uuid"] = "uuid"


# ─────────────────────────────────────────────
# A2E Host Config (Plugin-Centric)
# ─────────────────────────────────────────────
class A2EHostConfig(BaseModel):
    """
    A2E Host configuration.

    Host is now a thin runtime:
    - Loads plugins
    - Routes messages
    - Manages lifecycle

    All capability-specific config lives in plugins.
    """

    # ── Identity ─────────────────────────────
    host_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])

    # optional server config
    server: ServerConfig

    # optional auth
    auth_token: Optional[str] = None

    #  ── Transport (direct/http) ─────────────
    transport: TransportConfig

    # ── Audit ─────────────────────────────────────────────────────────────────
    audit: AuditConfig = Field(default_factory=AuditConfig)

    # ── Plugins (Core of system) ─────────────
    plugins: List[PluginConfig] = Field(default_factory=list)

    # ── Snapshot / Persistence ──────────────
    snapshot_store: Optional[SnapshotStoreConfig] = None
    snapshot_mode: str = "hybrid"  # "host" | "plugin" | "hybrid"

    # ── Observability / Audit ───────────────
    audit_log_path: Optional[Path] = None

    # ── Optional Global Policies ────────────
    # (rare; prefer plugin-level policies)
    global_limits: Dict[str, Any] = Field(default_factory=dict)

    # ───────────────────────────────────────
    # Validation Helpers
    # ───────────────────────────────────────
    def get_plugin(self, name: str) -> Optional[PluginConfig]:
        for p in self.plugins:
            if p.name == name:
                return p
        return None

    def enabled_plugins(self) -> List[PluginConfig]:
        return [p for p in self.plugins if p.enabled]
