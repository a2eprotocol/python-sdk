import pdb
import logging
import uuid
from pathlib import Path
from logging.handlers import RotatingFileHandler

from a2e.core.audit.schema import AuditEntry
from a2e.core.audit.logger import AuditLog


def build_audit_log(config: dict) -> AuditLog | None:
    """
    Builds an AuditLog from the `audit:` block in config.yaml.
    Returns None when audit.enabled is false or the block is missing.
    """
    cfg = config.audit

    if not cfg.enabled:
        return None

    # ── logger ──────────────────────────────────────────────────────────────
    logger = logging.getLogger("a2e.audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # keep audit lines out of the root logger

    if not logger.handlers:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(stream)

    # ── rotating file handler ────────────────────────────────────────────────
    #   config.audit.path is required when enabled; None → logger-only mode
    path: Path | None = None
    raw_path = cfg.path

    if raw_path:
        path = Path(raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        rot = cfg.rotate
        file_handler = RotatingFileHandler(
            filename=path,
            maxBytes=rot.max_bytes,      # 10485760  (10 MB)
            backupCount=rot.backup_count,  # 5
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(file_handler)

    return AuditLog(path=path, logger=logger)


def build_session_id(config: dict) -> str:
    """
    Resolves session_id from audit.session_id_source.

      host_id  →  use config.host_id   ("a2e-dev")
      uuid     →  fresh UUID each process start
    """
    source = config.audit

    if source == "host_id":
        return config["host_id"]  # "a2e-dev"

    return str(uuid.uuid4())


__all__ = [
    "AuditEntry",
    "AuditLog",
    "build_audit_log",
    "build_session_id"
]
