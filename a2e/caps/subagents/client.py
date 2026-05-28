from __future__ import annotations

from a2e.caps.subagents.protocol import (
    SubagentAwaitRequest,
    SubagentConfig,
    SubagentDelegateRequest,
    SubagentSpawnRequest,
    TaskDefinition,
)


class SubagentClient:
    def __init__(self, transport):
        self.transport = transport

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------
    async def spawn(
        self,
        *,
        name: str,
        model: str,
        role: str | None = None,
        system_prompt: str | None = None,
        capabilities: list[str] | None = None,
    ):

        request = SubagentSpawnRequest(
            agent=SubagentConfig(
                name=name,
                role=role,
                model=model,
                system_prompt=system_prompt,
                capabilities=capabilities or [],
            )
        )

        return await self.transport.send(request)

    # ------------------------------------------------------------------
    # Delegate
    # ------------------------------------------------------------------
    async def delegate(
        self,
        *,
        subagent_id: str,
        task_name: str,
        instruction: str,
        success_criteria: list[str] | None = None,
    ):
        request = SubagentDelegateRequest(
            subagent_id=subagent_id,
            task=TaskDefinition(
                name=task_name,
                instruction=instruction,
                success_criteria=success_criteria or [],
            ),
        )

        return await self.transport.send(request)

    # ------------------------------------------------------------------
    # Await
    # ------------------------------------------------------------------
    async def await_result(
        self,
        subagent_id: str,
    ):
        request = SubagentAwaitRequest(
            subagent_id=subagent_id,
        )

        return await self.transport.send(request)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    async def run(
        self,
        *,
        name: str,
        model: str,
        task_name: str,
        instruction: str,
    ):
        spawn_resp = await self.spawn(
            name=name,
            model=model,
        )

        subagent_id = spawn_resp.subagent_id

        await self.delegate(
            subagent_id=subagent_id,
            task_name=task_name,
            instruction=instruction,
        )

        return await self.await_result(subagent_id)
