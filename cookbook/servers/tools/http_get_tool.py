import requests
from typing import Dict, Any

from .tool_registry import register_tool, ToolDef


def http_get_tool(params: Dict[str, Any], config: Dict[str, Any]):
    url = params.get("url")
    resp = requests.get(url, timeout=10)
    return resp.text


register_tool(
    ToolDef(
        name="http_get",
        schema={
            "name": "http_get",
            "description": "Fetch content from a URL",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch"
                    }
                },
                "required": ["url"]
            },
            "tags": ["network", "http"]
        },
        func=http_get_tool,
        read_only=True,
        concurrent_safe=True,
    )
)
