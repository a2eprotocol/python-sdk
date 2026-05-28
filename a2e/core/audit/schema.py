from pydantic import BaseModel


class AuditEntry(BaseModel):
    ts: float
    session_id: str
    req_id: str
    correlation_id: str
    success: bool
    duration_ms: int
    error_code: str | None = None
    input_bytes: int = 0
    output_bytes: int = 0
