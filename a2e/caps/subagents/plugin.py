from __future__ import annotations

import asyncio
import uuid

from typing import Dict

from a2e.caps.subagents.protocol import (
    SubagentAwaitResponse,
    SubagentConfig,
    SubagentDelegateRequest,
    SubagentDelegateResponse,
    SubagentInfo,
    SubagentSpawnRequest,
    SubagentSpawnResponse,
    SubagentStatus,
)


class SubagentRuntime:
    def __init__(
        self,
        subagent_id: str,
        config: SubagentConfig,
        parent_agent_id: str | None = None,
        root_agent_id: str | None = None,
        depth: int = 0,
    ):
        self.subagent_id = subagent_id
        self.config = config

        self.parent_agent_id = parent_agent_id
        self.root_agent_id = root_agent_id

        self.depth = depth

        self.status = SubagentStatus.READY

        self.result = None

        self.task_handle: asyncio.Task | None = None

    async def run_task(self, request: SubagentDelegateRequest):
        self.status = SubagentStatus.RUNNING

        try:
            # ----------------------------------------------------------
            # Placeholder execution logic
            # Replace with actual agent adapter execution
            # ----------------------------------------------------------

            await asyncio.sleep(1)

            self.result = {
                "summary": f"Completed task: {request.task.name}",
                "instruction": request.task.instruction,
            }
            self.status = SubagentStatus.COMPLETED
        except Exception as exc:
            self.status = SubagentStatus.FAILED
            self.result = {
                "error": str(exc),
            }


class SubagentPlugin:
    def __init__(self):
        self.subagents: Dict[str, SubagentRuntime] = {}

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------
    async def spawn(
        self,
        request: SubagentSpawnRequest,
    ) -> SubagentSpawnResponse:
        subagent_id = f"sub_{uuid.uuid4().hex[:8]}"

        runtime = SubagentRuntime(
            subagent_id=subagent_id,
            config=request.agent,
            parent_agent_id=request.parent_agent_id,
            root_agent_id=request.root_agent_id,
            depth=0,
        )

        self.subagents[subagent_id] = runtime

        return SubagentSpawnResponse(
            subagent_id=subagent_id,
            status=SubagentStatus.READY,
        )

    # ------------------------------------------------------------------
    # Delegate
    # ------------------------------------------------------------------
    async def delegate(
        self,
        request: SubagentDelegateRequest,
    ) -> SubagentDelegateResponse:
        runtime = self.subagents[request.subagent_id]
        runtime.task_handle = asyncio.create_task(
            runtime.run_task(request)
        )
        return SubagentDelegateResponse(
            accepted=True,
            status=SubagentStatus.RUNNING,
        )

    # ------------------------------------------------------------------
    # Await
    # ------------------------------------------------------------------
    async def await_result(
        self,
        subagent_id: str,
    ) -> SubagentAwaitResponse:
        runtime = self.subagents[subagent_id]

        if runtime.task_handle:
            await runtime.task_handle

        return SubagentAwaitResponse(
            subagent_id=subagent_id,
            status=runtime.status,
            result=runtime.result,
        )

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------
    async def list_subagents(self):
        result = []
        for runtime in self.subagents.values():
            result.append(
                SubagentInfo(
                    subagent_id=runtime.subagent_id,
                    name=runtime.config.name,
                    status=runtime.status,
                    parent_agent_id=runtime.parent_agent_id,
                    root_agent_id=runtime.root_agent_id,
                    depth=runtime.depth,
                    config=runtime.config,
                )
            )

        return result

    # ------------------------------------------------------------------
    # Terminate
    # ------------------------------------------------------------------
    async def terminate(
        self,
        subagent_id: str,
    ):
        runtime = self.subagents[subagent_id]
        if runtime.task_handle:
            runtime.task_handle.cancel()

        runtime.status = SubagentStatus.TERMINATED
