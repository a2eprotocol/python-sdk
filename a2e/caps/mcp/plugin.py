# ---------------------------------------------------------------------------
# BASE MCP PLUGIN
# ---------------------------------------------------------------------------
import pdb
import time
from pydantic import BaseModel
from typing import Dict, Type, Optional

from a2e.caps.mcp.mcp_gateway import MCPGateway
from a2e.caps.base import (
    A2EMessage,
    A2EError
)

from a2e.caps.mcp.protocol import (
    MCPServerListResponse,
    MCPServerRegisterResponse,
    MCPServerUnregisterResponse,
    MCPResourceListResponse,
    MCPResourceReadResponse,
    MCPResourceContent,
    MCPResourceSubscribeResponse,
    MCPPromptListResponse,
    MCPPromptMessage,
    MCPPromptGetResponse,
    MCPRootsListResponse,
    MessageType,
    MCPServerConfig,
    MCPErrorCode,
    MCP_TYPE_MAP
)
from a2e.core.plugins import (
    A2EPlugin
)


class MCPPlugin(A2EPlugin):
    name = "mcp"
    priority = 10

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)
        self.tool_registry = config.get("tool_registry")
        self.send_fn = config.get("send_fn")
        self.sampling_fn = config.get("sampling_fn")
        self.roots = config.get("roots") or []

        self.gateway = MCPGateway(
            self.tool_registry,
            self.send_fn,
            self.sampling_fn,
            self.roots
        )

    # ---------------------------------------------------------
    # Supported Messages
    # ---------------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return MCP_TYPE_MAP

    # ---------------------------------------------------------
    # Main Handler
    # ---------------------------------------------------------
    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        response = None
        req_id = msg.id
        t0 = time.monotonic()

        try:
            t = msg.type

            if t == MessageType.MCP_SERVER_LIST_REQ:
                response = self._handle_server_list(msg)
            elif t == MessageType.MCP_SERVER_REGISTER_REQ:
                response = self._handle_register(msg)
            elif t == MessageType.MCP_SERVER_UNREGISTER_REQ:
                response = self._handle_unregister(msg)
            elif t == MessageType.MCP_RESOURCE_LIST_REQ:
                response = self._handle_resource_list(msg)
            elif t == MessageType.MCP_RESOURCE_READ_REQ:
                response = self._handle_resource_read(msg)
            elif t == MessageType.MCP_RESOURCE_SUBSCRIBE_REQ:
                response = self._handle_resource_subscribe(msg)
            elif t == MessageType.MCP_PROMPT_LIST_REQ:
                response = self._handle_prompt_list(msg)
            elif t == MessageType.MCP_PROMPT_GET_REQ:
                response = self._handle_prompt_get(msg)
            elif t == MessageType.MCP_ROOT_LIST_REQ:
                response = self._handle_root_list(msg)
            elif t == MessageType.MCP_SAMPLE_RESP:
                response = self._handle_sampling_response(msg)
            else:
                response = A2EError(
                    req_id=req_id,
                    code=MCPErrorCode.MCP_PROTOCOL_ERROR,
                    message=f"Unsupported MCP message: {t}",
                    retryable=False,
                )
        # -----------------------------------------------------
        # Exception Handling
        # -----------------------------------------------------
        except Exception as error:
            response = A2EError(
                req_id=req_id,
                code=MCPErrorCode.MCP_TRANSPORT_ERROR,
                message=str(error),
                retryable=False,
            )
        finally:
            self.audit_handle(msg, response, req_id, t0)

    # ---------------------------------------------------------
    # Server Management
    # ---------------------------------------------------------
    def _handle_server_list(self, msg):
        servers = self.gateway.list_servers()
        resp = MCPServerListResponse(req_id=msg.id, servers=servers)
        return resp

    def _handle_register(self, msg):
        config = MCPServerConfig(**msg.config)
        info = self.gateway.register(config)
        return MCPServerRegisterResponse(req_id=msg.id, info=info)

    def _handle_unregister(self, msg):
        ok = self.gateway.unregister(msg.server_id)
        return MCPServerUnregisterResponse(req_id=msg.id, success=ok)

    # ---------------------------------------------------------
    # Resources
    # ---------------------------------------------------------
    def _handle_resource_list(self, msg):
        resources, cursor = self.gateway.list_resources(
            server_id=msg.server_id or "",
            cursor=msg.cursor or ""
        )
        return MCPResourceListResponse(req_id=msg.id, resources=resources, cursor=cursor)

    def _handle_resource_read(self, msg):
        resp = self.gateway.read_resource(
            uri=msg.uri,
            server_id=msg.server_id or ""
        )

        # Normalize contents into MCPResourceContent dicts
        contents = []

        if getattr(resp, "contents", None):
            for c in resp.contents:
                # Already dict or dataclass → normalize
                if isinstance(c, dict):
                    contents.append(MCPResourceContent(**c).model_dump())
                else:
                    contents.append(MCPResourceContent(**c.__dict__).model_dump())

        return MCPResourceReadResponse(
            req_id=msg.req_id,
            server_id=getattr(resp, "server_id", msg.server_id or ""),
            contents=contents,
            error=getattr(resp, "error", "") or "",
        )

    def _handle_resource_subscribe(self, msg):
        ok = self.gateway.subscribe_resource(
            uri=msg.uri,
            server_id=msg.server_id or ""
        )
        return MCPResourceSubscribeResponse(req_id=msg.id, success=ok)

    # ---------------------------------------------------------
    # Prompts
    # ---------------------------------------------------------
    def _handle_prompt_list(self, msg):
        prompts = self.gateway.list_prompts(server_id=msg.server_id or "")
        return MCPPromptListResponse(req_id=msg.id, prompts=prompts)

    def _handle_prompt_get(self, msg):
        resp = self.gateway.get_prompt(
            name=msg.name,
            arguments=msg.arguments or {},
            server_id=msg.server_id or ""
        )

        # Normalize messages
        messages = []

        if getattr(resp, "messages", None):
            for m in resp.messages:
                if isinstance(m, dict):
                    messages.append(MCPPromptMessage(**m).model_dump())
                else:
                    messages.append(MCPPromptMessage(**vars(m)).model_dump())

        return MCPPromptGetResponse(
            req_id=msg.req_id,
            server_id=getattr(resp, "server_id", msg.server_id or ""),
            messages=messages,
            error=getattr(resp, "error", "") or "",
        )

    # ---------------------------------------------------------
    # Roots
    # ---------------------------------------------------------
    def _handle_root_list(self, msg):
        # roots are handled inside gateway callbacks,
        # but you can expose them explicitly if needed
        return MCPRootsListResponse(req_id=msg.id, roots=self.gateway._roots)

    # ---------------------------------------------------------
    # Sampling (LLM in the loop)
    # ---------------------------------------------------------
    def _handle_sampling_response(self, msg):
        """
        This is critical:
        Agent responds → we forward to MCP server via gateway
        """
        self.gateway.handle_sampling_response(msg)
        return None
