import pdb
from typing import List, Optional

from a2e.core.client import A2EClient
from a2e.caps.toolkits import (
    ToolkitListRequest,
    ToolkitListResponse,
    ToolkitConfigureRequest,
    ToolkitConfigureResponse,
    ToolkitDefinition,
    TOOLKIT_TYPE_MAP
)


class ToolkitAPI:
    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(TOOLKIT_TYPE_MAP)

    # -----------------------------------------------------
    # LIST TOOLKITS
    # -----------------------------------------------------
    def list(
        self,
        filter_kind: str = "",
        filter_tags: Optional[List[str]] = None,
        timeout: int = 10,
    ) -> List[ToolkitDefinition]:

        req = ToolkitListRequest(
            filter_kind=filter_kind,
            filter_tags=filter_tags or [],
        )

        resp = self._c.rpc(req, timeout=timeout)

        if not isinstance(resp, ToolkitListResponse):
            raise ConnectionError(
                f"Unexpected toolkit list response: {type(resp)}"
            )

        return resp.toolkits

    # -----------------------------------------------------
    # CONFIGURE TOOLKIT
    # -----------------------------------------------------
    def configure(
        self,
        name: str,
        schema: dict | None = None,
        timeout: int = 200,
    ) -> ToolkitDefinition:

        req = ToolkitConfigureRequest(
            name=name,
            schema=schema or {},
        )

        resp = self._c.rpc(req, timeout=timeout)

        if not isinstance(resp, ToolkitConfigureResponse):
            raise ConnectionError(
                f"Unexpected toolkit configure response: {type(resp)}"
            )

        if resp.error:
            raise RuntimeError(f"Toolkit configure failed: {resp.error}")

        return resp.toolkit

    # -----------------------------------------------------
    # ENSURE CONFIGURED (idempotent helper)
    # -----------------------------------------------------
    def ensure(
        self,
        name: str,
        schema: dict | None = None,
        timeout: int = 20,
    ) -> ToolkitDefinition:
        """
        Idempotent helper:
        - checks if already configured
        - otherwise configures it
        """

        toolkits = self.list(timeout=timeout)

        for tk in toolkits:
            if tk.name == name and tk.configured:
                return tk

        return self.configure(name=name, schema=schema, timeout=timeout)

    # -----------------------------------------------------
    # GET TOOLKIT BY NAME
    # -----------------------------------------------------
    def get(
        self,
        name: str,
        timeout: int = 10,
    ) -> Optional[ToolkitDefinition]:

        toolkits = self.list(timeout=timeout)

        for tk in toolkits:
            if tk.name == name:
                return tk

        return None
