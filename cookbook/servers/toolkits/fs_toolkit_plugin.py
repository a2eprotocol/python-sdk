import pdb
from typing import List
from xa.tools.toolkit.content.file_system import (
    FileSystemToolkit,
    FileSystemSchema
)

from a2e.caps.toolkits import (
    ToolkitPlugin,
    ToolkitListRequest,
    ToolkitListResponse,
    ToolkitDefinition
)


class FileSystemToolkitPlugin(ToolkitPlugin):

    # -----------------------------------------------------
    # Internal: build definition from class
    # -----------------------------------------------------
    def _build_definition(self):
        return ToolkitDefinition(
            name="filesystem",
            alias=FileSystemToolkit.__alias__,
            description=FileSystemToolkit.__description__,
            category=FileSystemToolkit.__category__,
            tags=FileSystemToolkit.__tags__.split(","),
            icon_svg=FileSystemToolkit.__icon_svg__,
            schema=FileSystemToolkit.__schema__.model_json_schema(),
            tools=FileSystemToolkit.__toollist__,
            configured=False,
            version="1.0.0"
        )

    # -----------------------------------------------------
    # LIST TOOLKITS (no instantiation)
    # -----------------------------------------------------
    def _list_toolkits(self, msg):
        toolkit = self._build_definition()
        return ToolkitListResponse(
            req_id=msg.id,
            toolkits=[toolkit]
        )

    # -----------------------------------------------------
    # CONFIGURE TOOLKIT (runtime instantiation)
    # -----------------------------------------------------
    def _configure_toolkit(self, msg):
        """
        msg.schema → config payload from agent/UI
        """

        # 1. Build schema object
        schema = FileSystemToolkit.create_schema(msg.schema or {})

        # 2. Instantiate toolkit
        toolkit = FileSystemToolkit(
            schema=schema,
            logger=self.host.logger,
        )
        # 3. Register toolkit tools into ToolRegistry
        # IMPORTANT: toolkit must expose actual tool runners
        for tool_name in FileSystemToolkit.__toollist__:
            runner = toolkit.get_tool(tool_name)  # assumed API

            manifest = self._build_tool_manifest(tool_name)

            self.host.tool_registry.register(
                ToolEntry(
                    manifest=manifest,
                    runner=runner
                )
            )

        # 4. Return configured definition
        definition = self._build_definition()
        definition.configured = True

        return definition

    # -----------------------------------------------------
    # Build ToolManifest per tool
    # -----------------------------------------------------
    def _build_tool_manifest(self, tool_name: str):
        from .protocol import ToolManifest, ToolKind

        return ToolManifest(
            name=f"filesystem__{tool_name}",
            kind=ToolKind.CUSTOM.value,
            description=f"[filesystem] {tool_name}",
            input_schema=FileSystemToolkit.__schema__.model_json_schema(),
            streaming=False,
            idempotent=False,
            tags=["filesystem", tool_name],
            version="1.0.0",
        )
