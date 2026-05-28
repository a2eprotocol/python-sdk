from .tool_registry import register_tool, ToolDef


def read_file_tool(params, config):
    path = params.get("path")
    with open(path, "r") as f:
        return f.read()


register_tool(
    ToolDef(
        name="Read",
        schema={
            "name": "read_file",
            "description": "Read contents of a file",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path"
                    }
                },
                "required": ["path"]
            },
            "tags": ["filesystem"]
        },
        func=read_file_tool,
        read_only=True,
        concurrent_safe=True,
    )
)
