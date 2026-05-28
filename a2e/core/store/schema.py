from pydantic import BaseModel, Field
from typing import Dict, Any


class SnapshotStoreConfig(BaseModel):
    """
    Config for snapshot persistence backend.
    """

    type: str = "file"                 # "file" | "sqlite" | "custom"
    config: Dict[str, Any] = Field(default_factory=dict)
