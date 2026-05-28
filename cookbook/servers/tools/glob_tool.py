import glob

from .tool_registry import register_tool, ToolDef


# ─────────────────────────────────────────────
# GLOB TOOL
# ─────────────────────────────────────────────
def glob_tool(params, config):
    pattern = params.get("pattern")
    recursive = params.get("recursive", True)

    if not pattern:
        return "Error: 'pattern' is required"

    try:
        matches = glob.glob(pattern, recursive=recursive)

        # limit output
        max_results = params.get("limit", 100)
        matches = matches[:max_results]

        return "\n".join(matches)

    except Exception as e:
        return f"Error in glob: {e}"


register_tool(
    ToolDef(
        name="Glob",
        schema={
            "name": "Glob",
            "description": "Find files matching a pattern (supports ** for recursion)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (e.g., **/*.py)"
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Enable recursive search",
                        "default": True
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": 100
                    }
                },
                "required": ["pattern"]
            },
            "tags": ["filesystem", "search"]
        },
        func=glob_tool,
        read_only=True,
        concurrent_safe=True,
    )
)
