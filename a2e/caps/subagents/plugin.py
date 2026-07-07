from __future__ import annotations

import asyncio
import threading
import uuid
from concurrent.futures import Future as ConcurrentFuture
from typing import Dict, Optional

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

        self.task_handle: Optional[ConcurrentFuture] = None

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
    """In-memory subagent lifecycle manager.

    DESIGN NOTE (loop ownership): subagent tasks are executed on a dedicated
    long-lived event loop owned by this plugin (run in a background thread),
    NOT on the caller's event loop. This prevents the silent-cancellation bug
    where a subagent task scheduled via `asyncio.create_task` on the caller's
    loop is cancelled when that loop is torn down between `delegate()` and
    `await_result()` (e.g. each call wrapped in its own `asyncio.run()`).

    Callers may invoke `spawn`/`delegate`/`await_result` from any event loop or
    from synchronous code; the plugin bridges to its owned loop via
    `asyncio.run_coroutine_threadsafe`.
    """

    def __init__(self):
        self.subagents: Dict[str, SubagentRuntime] = {}

        # --- Owned event loop (background thread) -------------------
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._loop_thread.start()

    def _submit(self, coro):
        """Schedule `coro` on the plugin's owned loop; returns a concurrent
        future the caller can `.result()` on (blocking) from any context."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def shutdown(self):
        """Stop the owned loop. Call on plugin teardown."""
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=2)
        if not self._loop.is_closed():
            self._loop.close()

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------
    def spawn(self, request: SubagentSpawnRequest) -> SubagentSpawnResponse:
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
    def delegate(
        self, request: SubagentDelegateRequest
    ) -> SubagentDelegateResponse:
        runtime = self.subagents[request.subagent_id]

        # Schedule the task on the plugin's OWNED loop, not the caller's.
        # The task survives regardless of what happens to the caller's loop.
        runtime.task_handle = self._submit(runtime.run_task(request))

        return SubagentDelegateResponse(
            accepted=True,
            status=SubagentStatus.RUNNING,
        )

    # ------------------------------------------------------------------
    # Await
    # ------------------------------------------------------------------
    def await_result(self, subagent_id: str) -> SubagentAwaitResponse:
        runtime = self.subagents[subagent_id]

        if runtime.task_handle is not None:
            # Blocks the caller until the owned-loop task completes. Safe even
            # if the caller has no event loop or a different one.
            try:
                runtime.task_handle.result()
            except Exception:
                # run_task's own try/except already set FAILED/result; the
                # concurrent.futures wrapper re-raises, so swallow it here.
                pass

        return SubagentAwaitResponse(
            subagent_id=subagent_id,
            status=runtime.status,
            result=runtime.result,
        )

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------
    def list_subagents(self):
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
    def terminate(self, subagent_id: str):
        runtime = self.subagents[subagent_id]
        if runtime.task_handle is not None:
            runtime.task_handle.cancel()

        runtime.status = SubagentStatus.TERMINATED
