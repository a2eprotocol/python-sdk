import os
import re

from .tool_registry import register_tool, ToolDef


# ─────────────────────────────────────────────
# GREP TOOL
# ─────────────────────────────────────────────
def grep_tool(params, config):
    pattern = params.get("pattern")
    path = params.get("path")
    ignore_case = params.get("ignore_case", True)

    if not pattern or not path:
        return "Error: 'pattern' and 'path' are required"

    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(pattern, flags)

    results = []

    try:
        # if path is file
        if os.path.isfile(path):
            files = [path]
        else:
            files = []
            for root, _, filenames in os.walk(path):
                for f in filenames:
                    files.append(os.path.join(root, f))

        max_results = params.get("limit", 100)

        for file in files:
            try:
                with open(file, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f"{file}:{i}: {line.strip()}")

                            if len(results) >= max_results:
                                return "\n".join(results)

            except Exception:
                continue

        return "\n".join(results)

    except Exception as e:
        return f"Error in grep: {e}"


register_tool(
    ToolDef(
        name="Grep",
        schema={
            "name": "Grep",
            "description": "Search for a pattern inside files or directories",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search"
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory path"
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "default": True
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100
                    }
                },
                "required": ["pattern", "path"]
            },
            "tags": ["filesystem", "search", "text"]
        },
        func=grep_tool,
        read_only=True,
        concurrent_safe=True,
    )
)
