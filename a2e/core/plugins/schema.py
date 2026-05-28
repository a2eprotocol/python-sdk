from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, Optional


class PluginMeta(BaseModel):
    enabled: bool = True
    priority: int = 0                  # routing priority
    exclusive: bool = False            # single handler vs broadcast
    model_config = ConfigDict(extra="allow")


# ─────────────────────────────────────────────
# Plugin Config
# ─────────────────────────────────────────────
class PluginConfig(BaseModel):
    """
    Defines a pluggable subsystem in the A2E host.
    """
    name: str                          # unique instance name
    type: str
    cls: str                           # import path (e.g. a2e.plugins.memory.MemoryPlugin)
    metadata: Optional[PluginMeta] = Field(default_factory=PluginMeta) 
