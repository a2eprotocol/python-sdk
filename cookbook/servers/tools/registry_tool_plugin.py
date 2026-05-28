import pdb
import time
import importlib
from typing import List, Dict, Any

from a2e.caps.tools import (
    ToolPlugin,
    ToolResult,
    ToolDefinition,
    ToolParameter,
)

# External registry (your system)
from .tool_registry import (
    get_all_tools,
    execute_tool,
)


# ─────────────────────────────────────────────
# ToolPlugin (Flat tools, no toolkit)
# ─────────────────────────────────────────────

class RegistryToolPlugin(ToolPlugin):
    """
    A2E ToolPlugin backed by external ToolDef registry.

    Responsibilities:
    - tool/list → List[ToolDefinition]
    - tool/call → execute tool
    """

    name = "registry_tools"

    def __init__(self, host_instance, config=None):
        super().__init__(host_instance, config)
        self._init_registry()

    def _init_registry(self):
        modules = self.config.get("tool_modules", [])

        for mod_path in modules:
            try:
                importlib.import_module(mod_path)
            except Exception as e:
                print(f"[tool] failed to load {mod_path}: {e}")

    # ─────────────────────────────────────────
    # TOOL LIST
    # ─────────────────────────────────────────
    def _list_tools(self) -> List[ToolDefinition]:
        try:
            tools = get_all_tools()
            tool_defs: List[ToolDefinition] = []

            for tool in tools:
                try:
                    tool_defs.append(self._to_tool_definition(tool))
                    return tool_defs
                except Exception as e:
                    print(f"[tool] failed to convert {tool.name}: {str(e)}")
        except Exception as e:
            print(f"[tool] failed to list {str(e)}")
            raise

    # ─────────────────────────────────────────
    # TOOL EXECUTION
    # ─────────────────────────────────────────
    def _execute_tool(self, tool_name, arguments) -> ToolResult:
        start = time.time()

        try:
            result = execute_tool(
                name=tool_name,
                params=arguments or {},
                config=self.config,
            )

            duration_ms = int((time.time() - start) * 1000)

            # Heuristic: detect truncation marker from registry
            truncated = isinstance(result, str) and "[... " in result and "truncated ...]" in result

            return ToolResult(
                success=True,
                tool_name=tool_name,
                data=result,
                summary=str(result)[:500] if result else None,
                truncated=truncated,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)

            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=str(e),
                error_code="tool_execution_error",
                duration_ms=duration_ms,
            )

    # ─────────────────────────────────────────
    # SCHEMA CONVERSION
    # ─────────────────────────────────────────
    def _to_tool_definition(self, tool) -> ToolDefinition:
        schema = tool.schema or {}

        return ToolDefinition(
            name=tool.name,
            description=schema.get("description", ""),
            input_parameters=self._parse_parameters(schema),
            output_parameters=[],
            streaming=False,
            idempotent=tool.read_only,
            tags=schema.get("tags", []),
            version=schema.get("version", "1.0.0"),
        )

    def _parse_parameters(self, schema: dict) -> List[ToolParameter]:
        input_schema = schema.get("input_schema", {})
        properties = input_schema.get("properties", {})
        required_fields = input_schema.get("required", [])

        return self._parse_properties(properties, required_fields)

    def _parse_properties(
        self,
        properties: Dict[str, Any],
        required_fields: List[str],
    ) -> List[ToolParameter]:

        params: List[ToolParameter] = []

        for name, prop in properties.items():
            param = ToolParameter(
                name=name,
                type=prop.get("type", "string"),
                description=prop.get("description", ""),
                required=name in required_fields,
                enum=prop.get("enum"),
            )

            # Nested object support
            if prop.get("type") == "object":
                nested_props = prop.get("properties", {})
                nested_required = prop.get("required", [])

                param.properties = {
                    k: ToolParameter(
                        name=k,
                        type=v.get("type", "string"),
                        description=v.get("description", ""),
                        required=k in nested_required,
                    )
                    for k, v in nested_props.items()
                }

            params.append(param)

        return params
