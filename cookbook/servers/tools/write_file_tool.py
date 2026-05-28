from .tool_registry import register_tool, ToolDef


def write_file_tool(params, config):
    path = params.get("path")
    content = params.get("content")

    with open(path, "w") as f:
        f.write(content)

    return "OK"


register_tool(
    ToolDef(
        name="write_file",
        schema={
            "name": "write_file",
            "description": "Write content to a file",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            },
            "tags": ["filesystem", "write"]
        },
        func=write_file_tool,
        read_only=False,
        concurrent_safe=False,
    )
)
