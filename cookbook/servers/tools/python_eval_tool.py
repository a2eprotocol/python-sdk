from .tool_registry import register_tool, ToolDef


def python_eval_tool(params, config):
    code = params.get("code")

    local_scope = {}
    exec(code, {}, local_scope)

    return str(local_scope)


register_tool(
    ToolDef(
        name="python_eval",
        schema={
            "name": "python_eval",
            "description": "Execute Python code",
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"}
                },
                "required": ["code"]
            },
            "tags": ["python", "execution"]
        },
        func=python_eval_tool,
        read_only=False,
        concurrent_safe=False,
    )
)
