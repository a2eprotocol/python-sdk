from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
import json
import hashlib
import requests
import os

# ─────────────────────────────────────────────
# Tool Definition
# ─────────────────────────────────────────────

@dataclass
class ToolDef:
    name: str
    schema: Dict[str, Any]
    func: Callable[[Dict[str, Any], Dict[str, Any]], Any]
    read_only: bool = False
    concurrent_safe: bool = False


# ─────────────────────────────────────────────
# Registry + Cache
# ─────────────────────────────────────────────

_registry: Dict[str, ToolDef] = {}

_cache: Dict[str, Any] = {}
_cache_order: List[str] = []
_CACHE_MAX = 64


def _cache_key(name: str, params: Dict[str, Any]) -> str:
    raw = json.dumps({"n": name, "p": params}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def clear_tool_cache():
    _cache.clear()
    _cache_order.clear()


# ─────────────────────────────────────────────
# Registry APIs
# ─────────────────────────────────────────────

def register_tool(tool_def: ToolDef):
    _registry[tool_def.name] = tool_def


def get_tool(name: str) -> Optional[ToolDef]:
    return _registry.get(name)


def get_all_tools() -> List[ToolDef]:
    return list(_registry.values())


def execute_tool(
    name: str,
    params: Dict[str, Any],
    config: Dict[str, Any],
    max_output: int = 32000,
):
    tool = get_tool(name)
    if not tool:
        raise ValueError(f"Tool '{name}' not found")

    # Cache for read-only tools
    if tool.read_only:
        key = _cache_key(name, params)
        if key in _cache:
            return _cache[key]

    else:
        clear_tool_cache()

    result = tool.func(params, config)

    if tool.read_only:
        key = _cache_key(name, params)
        _cache[key] = result
        _cache_order.append(key)

        if len(_cache_order) > _CACHE_MAX:
            old = _cache_order.pop(0)
            _cache.pop(old, None)

    # Truncate large outputs
    if isinstance(result, str) and len(result) > max_output:
        result = result[:max_output]

    return result
