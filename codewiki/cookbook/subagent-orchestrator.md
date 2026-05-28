# Subagent Orchestrator Plugin & Client Example

```text
a2e/caps/subagents/plugin.py   — SubagentPlugin, SubagentRuntime
a2e/caps/subagents/client.py   — SubagentClient
a2e/caps/subagents/protocol.py — 12 message types, SubagentConfig, TaskDefinition, SubagentInfo
```

## Overview

This cookbook walks through building a production-grade subagent orchestration plugin (host side) and consuming it from a parent agent (client side). The subagents capability provides multi-agent orchestration — spawning child agents, delegating tasks, awaiting results, inter-agent messaging, and merging outputs.

The core flow is: **Spawn → Delegate → Await → Merge**. A parent agent creates one or more subagents, assigns them tasks, waits for completion, and combines results.

## Plugin Side: Orchestrator Plugin with Depth Control

The built-in `SubagentPlugin` provides basic spawn/delegate/await/terminate. Below is an extended version that adds depth limiting, resource quotas, event emission, inter-agent messaging, and merge strategies.

```python
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, Optional

from a2e.core.plugins.interface import A2EPlugin
from a2e.caps.subagents.protocol import (
    SubagentAwaitRequest,
    SubagentAwaitResponse,
    SubagentCancelRequest,
    SubagentConfig,
    SubagentDelegateRequest,
    SubagentDelegateResponse,
    SubagentEvent,
    SubagentInfo,
    SubagentListRequest,
    SubagentListResponse,
    SubagentMergeRequest,
    SubagentMergeResponse,
    SubagentMessagePayload,
    SubagentMessageRequest,
    SubagentMessageResponse,
    SubagentSpawnRequest,
    SubagentSpawnResponse,
    SubagentStatus,
    SubagentTerminateRequest,
    MemoryScope,
    ToolScope,
)

logger = logging.getLogger("subagent.orchestrator")


class OrchestratorRuntime:
    """Runtime state for a single subagent instance."""

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
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.task_handle: Optional[asyncio.Task] = None
        self.mailbox: list[SubagentMessagePayload] = []

    async def run_task(self, task: SubagentDelegateRequest):
        """Execute a delegated task. Replace with real agent adapter logic."""
        self.status = SubagentStatus.RUNNING
        try:
            # ----------------------------------------------------------
            # Placeholder: replace with actual agent adapter execution.
            # In production, this would:
            #   1. Build a prompt from task.instruction + success_criteria
            #   2. Call the LLM model specified in self.config.model
            #   3. Let the agent use its configured capabilities
            #   4. Collect the final output
            # ----------------------------------------------------------
            await asyncio.sleep(1)  # Simulate work

            self.result = {
                "summary": f"Completed task: {task.task.name}",
                "instruction": task.task.instruction,
                "success_criteria_met": task.task.success_criteria,
            }
            self.status = SubagentStatus.COMPLETED
        except asyncio.CancelledError:
            self.status = SubagentStatus.CANCELLED
            raise
        except Exception as exc:
            self.status = SubagentStatus.FAILED
            self.error = str(exc)
            self.result = {"error": str(exc)}


class OrchestratorPlugin(A2EPlugin):
    """Production-grade subagent orchestrator with depth control,
    resource quotas, event emission, and merge strategies."""

    name = "subagent_orchestrator"
    type = "subagents"
    priority = 0

    # Configurable limits
    MAX_DEPTH = 3
    MAX_SUBAGENTS_PER_SESSION = 10
    DEFAULT_TIMEOUT = 600

    def setup(self, host, config):
        super().setup(host, config)
        self.subagents: Dict[str, OrchestratorRuntime] = {}
        self.max_depth = config.get("max_depth", self.MAX_DEPTH)
        self.max_per_session = config.get(
            "max_subagents_per_session", self.MAX_SUBAGENTS_PER_SESSION
        )
        self._event_callback = None
        logger.info(
            "OrchestratorPlugin ready (max_depth=%d, max_per_session=%d)",
            self.max_depth,
            self.max_per_session,
        )

    def set_event_callback(self, cb):
        """Register callback for emitting SubagentEvents to the parent."""
        self._event_callback = cb

    def _emit_event(self, subagent_id: str, event: str, content: dict | None = None):
        """Emit a lifecycle event to the parent agent."""
        if self._event_callback:
            evt = SubagentEvent(
                subagent_id=subagent_id,
                event=event,
                content=content or {},
            )
            self._event_callback(evt)

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    def supported_messages(self) -> dict[str, type]:
        return {
            "SUBAGENT_SPAWN_REQ": SubagentSpawnRequest,
            "SUBAGENT_DELEGATE_REQ": SubagentDelegateRequest,
            "SUBAGENT_AWAIT_REQ": SubagentAwaitRequest,
            "SUBAGENT_MESSAGE_REQ": SubagentMessageRequest,
            "SUBAGENT_LIST_REQ": SubagentListRequest,
            "SUBAGENT_CANCEL_REQ": SubagentCancelRequest,
            "SUBAGENT_TERMINATE_REQ": SubagentTerminateRequest,
            "SUBAGENT_MERGE_REQ": SubagentMergeRequest,
        }

    async def handle(self, msg):
        dispatch = {
            SubagentSpawnRequest: self._on_spawn,
            SubagentDelegateRequest: self._on_delegate,
            SubagentAwaitRequest: self._on_await,
            SubagentMessageRequest: self._on_message,
            SubagentListRequest: self._on_list,
            SubagentCancelRequest: self._on_cancel,
            SubagentTerminateRequest: self._on_terminate,
            SubagentMergeRequest: self._on_merge,
        }
        handler = dispatch.get(type(msg))
        if handler:
            return await handler(msg)
        return None

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------

    async def _on_spawn(self, msg: SubagentSpawnRequest) -> SubagentSpawnResponse:
        # Enforce resource quota
        if len(self.subagents) >= self.max_per_session:
            logger.warning("Subagent quota reached (%d)", self.max_per_session)
            return SubagentSpawnResponse(
                subagent_id="",
                status=SubagentStatus.FAILED,
            )

        # Enforce depth limit
        current_depth = 0
        if msg.parent_agent_id and msg.parent_agent_id in self.subagents:
            current_depth = self.subagents[msg.parent_agent_id].depth + 1
        if current_depth > self.max_depth:
            logger.warning("Depth limit reached (%d)", self.max_depth)
            return SubagentSpawnResponse(
                subagent_id="",
                status=SubagentStatus.FAILED,
            )

        # Apply safe defaults
        config = msg.agent
        if config.timeout_seconds <= 0:
            config.timeout_seconds = self.DEFAULT_TIMEOUT
        if config.memory_scope not in (
            MemoryScope.SHARED,
            MemoryScope.ISOLATED,
            MemoryScope.SNAPSHOT,
        ):
            config.memory_scope = MemoryScope.ISOLATED
        if config.tool_scope not in (
            ToolScope.SHARED,
            ToolScope.RESTRICTED,
            ToolScope.ISOLATED,
        ):
            config.tool_scope = ToolScope.RESTRICTED

        subagent_id = f"sub_{uuid.uuid4().hex[:8]}"
        runtime = OrchestratorRuntime(
            subagent_id=subagent_id,
            config=config,
            parent_agent_id=msg.parent_agent_id,
            root_agent_id=msg.root_agent_id,
            depth=current_depth,
        )
        self.subagents[subagent_id] = runtime

        self._emit_event(
            subagent_id, "spawned", {"name": config.name, "role": config.role}
        )
        logger.info("Spawned subagent %s (%s)", subagent_id, config.name)

        return SubagentSpawnResponse(
            subagent_id=subagent_id,
            status=SubagentStatus.READY,
        )

    # ------------------------------------------------------------------
    # Delegate
    # ------------------------------------------------------------------

    async def _on_delegate(
        self, msg: SubagentDelegateRequest
    ) -> SubagentDelegateResponse:
        runtime = self.subagents.get(msg.subagent_id)
        if not runtime:
            return SubagentDelegateResponse(
                accepted=False,
                status=SubagentStatus.FAILED,
            )
        if runtime.status != SubagentStatus.READY:
            return SubagentDelegateResponse(
                accepted=False,
                status=runtime.status,
            )

        # Launch task as asyncio.Task with timeout guard
        async def _guarded_run():
            try:
                await asyncio.wait_for(
                    runtime.run_task(msg),
                    timeout=runtime.config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                runtime.status = SubagentStatus.FAILED
                runtime.error = f"Timeout after {runtime.config.timeout_seconds}s"
                self._emit_event(
                    msg.subagent_id, "timeout", {"timeout_seconds": runtime.config.timeout_seconds}
                )
            finally:
                self._emit_event(
                    msg.subagent_id,
                    "status_changed",
                    {"status": runtime.status.value},
                )

        runtime.task_handle = asyncio.create_task(_guarded_run())

        self._emit_event(
            msg.subagent_id,
            "delegated",
            {"task": msg.task.name},
        )

        return SubagentDelegateResponse(
            accepted=True,
            status=SubagentStatus.RUNNING,
        )

    # ------------------------------------------------------------------
    # Await
    # ------------------------------------------------------------------

    async def _on_await(self, msg: SubagentAwaitRequest) -> SubagentAwaitResponse:
        runtime = self.subagents.get(msg.subagent_id)
        if not runtime:
            return SubagentAwaitResponse(
                subagent_id=msg.subagent_id,
                status=SubagentStatus.FAILED,
                error="Unknown subagent",
            )

        if runtime.task_handle:
            await runtime.task_handle

        return SubagentAwaitResponse(
            subagent_id=msg.subagent_id,
            status=runtime.status,
            result=runtime.result,
            error=runtime.error,
        )

    # ------------------------------------------------------------------
    # Inter-agent messaging
    # ------------------------------------------------------------------

    async def _on_message(
        self, msg: SubagentMessageRequest
    ) -> SubagentMessageResponse:
        target = self.subagents.get(msg.to_subagent_id)
        if not target:
            return SubagentMessageResponse(delivered=False)

        target.mailbox.append(msg.message)
        self._emit_event(
            msg.to_subagent_id,
            "message_received",
            {"from": msg.from_subagent_id},
        )
        return SubagentMessageResponse(delivered=True)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def _on_list(self, msg: SubagentListRequest) -> SubagentListResponse:
        infos = [
            SubagentInfo(
                subagent_id=r.subagent_id,
                name=r.config.name,
                status=r.status,
                parent_agent_id=r.parent_agent_id,
                root_agent_id=r.root_agent_id,
                depth=r.depth,
                config=r.config,
            )
            for r in self.subagents.values()
        ]
        return SubagentListResponse(subagents=infos)

    # ------------------------------------------------------------------
    # Cancel / Terminate
    # ------------------------------------------------------------------

    async def _on_cancel(self, msg: SubagentCancelRequest):
        runtime = self.subagents.get(msg.subagent_id)
        if runtime and runtime.task_handle:
            runtime.task_handle.cancel()
            runtime.status = SubagentStatus.CANCELLED
            self._emit_event(msg.subagent_id, "cancelled")
        return None  # Fire-and-forget per spec

    async def _on_terminate(self, msg: SubagentTerminateRequest):
        runtime = self.subagents.get(msg.subagent_id)
        if runtime and runtime.task_handle:
            runtime.task_handle.cancel()
        if runtime:
            runtime.status = SubagentStatus.TERMINATED
            self._emit_event(msg.subagent_id, "terminated")
            # Propagate cancellation to child subagents
            for child_id, child in self.subagents.items():
                if child.parent_agent_id == msg.subagent_id:
                    if child.task_handle:
                        child.task_handle.cancel()
                    child.status = SubagentStatus.TERMINATED
                    self._emit_event(child_id, "terminated_parent")
        return None

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    async def _on_merge(self, msg: SubagentMergeRequest) -> SubagentMergeResponse:
        results = {}
        for sid in msg.subagent_ids:
            runtime = self.subagents.get(sid)
            if runtime and runtime.result:
                results[sid] = runtime.result

        strategy = msg.strategy
        if strategy == "hierarchical_summary":
            merged = self._merge_hierarchical(results)
        elif strategy == "voting":
            merged = self._merge_voting(results)
        else:
            merged = self._merge_custom(results, strategy)

        self._emit_event("all", "merged", {"strategy": strategy, "count": len(results)})
        return SubagentMergeResponse(merged_result=merged)

    def _merge_hierarchical(self, results: dict) -> dict:
        """Parent summarizes child results into a single summary."""
        summaries = []
        for sid, res in results.items():
            summaries.append(f"[{sid}] {res.get('summary', str(res))}")
        return {
            "strategy": "hierarchical_summary",
            "summary": "\n".join(summaries),
            "source_count": len(results),
        }

    def _merge_voting(self, results: dict) -> dict:
        """Majority vote across subagent results."""
        from collections import Counter

        answers = [str(r) for r in results.values()]
        vote_counts = Counter(answers)
        winner, count = vote_counts.most_common(1)[0]
        return {
            "strategy": "voting",
            "winner": winner,
            "votes": count,
            "total": len(answers),
        }

    def _merge_custom(self, results: dict, strategy_name: str) -> dict:
        """Pass-through for host-defined merge strategies."""
        return {
            "strategy": strategy_name,
            "results": results,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def teardown(self):
        for runtime in self.subagents.values():
            if runtime.task_handle:
                runtime.task_handle.cancel()
        self.subagents.clear()
```

### Register in Config

```yaml
plugins:
  - name: subagent_orchestrator
    type: subagents
    cls: my_package.subagents.OrchestratorPlugin
    metadata:
      max_depth: 3
      max_subagents_per_session: 10
```

## Client Side: Parent Agent Orchestration

The `SubagentClient` provides `spawn`, `delegate`, `await_result`, and the convenience `run` method. Below are practical patterns for common orchestration scenarios.

### Setup

```python
import asyncio
import logging

from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.subagents.client import SubagentClient

logger = logging.getLogger("parent-agent")

# --- Setup ---
config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
transport = server.start()

client = A2EClient(transport, logger, agent_caps=["subagents"])
client.connect()

subagents = SubagentClient(client)
```

### 1. Single Subagent — Fire and Await

The simplest pattern: spawn one subagent, give it a task, wait for the result.

```python
async def run_single_task():
    # Spawn a researcher subagent
    spawn_resp = await subagents.spawn(
        name="researcher",
        model="claude-3.5-sonnet",
        role="research",
        system_prompt="You are a research assistant. Provide concise, factual summaries.",
        capabilities=["tools", "memory"],
    )
    subagent_id = spawn_resp.subagent_id
    print(f"Spawned: {subagent_id} (status={spawn_resp.status})")

    # Delegate a research task
    delegate_resp = await subagents.delegate(
        subagent_id=subagent_id,
        task_name="research_quantum",
        instruction="Research the latest developments in quantum computing error correction",
        success_criteria=[
            "Include at least 3 recent papers",
            "Provide a technical summary",
        ],
    )
    print(f"Delegated: accepted={delegate_resp.accepted}, status={delegate_resp.status}")

    # Await the result
    result = await subagents.await_result(subagent_id)
    if result.status == "COMPLETED":
        print(f"Result: {result.result}")
    else:
        print(f"Failed: {result.error}")

    return result
```

### 2. Convenience: spawn + delegate + await in one call

The `run()` method chains spawn, delegate, and await for the simplest use case:

```python
async def run_convenience():
    result = await subagents.run(
        name="coder",
        model="gpt-4",
        task_name="implement_endpoint",
        instruction="Implement a REST API endpoint for user authentication",
    )
    print(f"Status: {result.status}")
    print(f"Result: {result.result}")
    return result
```

### 3. Parallel Subagents — Fan-out / Fan-in

Spawn multiple subagents for parallel work, then await all results.

```python
async def run_parallel():
    # Define tasks for different specialist subagents
    tasks = [
        {
            "name": "researcher",
            "model": "claude-3.5-sonnet",
            "role": "research",
            "task_name": "market_research",
            "instruction": "Analyze the current market for AI agent frameworks",
            "system_prompt": "You are a market research analyst.",
        },
        {
            "name": "coder",
            "model": "gpt-4",
            "role": "engineering",
            "task_name": "poc_implementation",
            "instruction": "Build a proof-of-concept REST API for agent orchestration",
            "system_prompt": "You are a senior software engineer.",
        },
        {
            "name": "writer",
            "model": "claude-3.5-sonnet",
            "role": "documentation",
            "task_name": "write_docs",
            "instruction": "Draft API documentation for the agent orchestration endpoint",
            "system_prompt": "You are a technical writer.",
        },
    ]

    # Spawn and delegate all subagents
    subagent_ids = []
    for t in tasks:
        spawn_resp = await subagents.spawn(
            name=t["name"],
            model=t["model"],
            role=t["role"],
            system_prompt=t["system_prompt"],
            capabilities=["tools", "memory"],
        )
        sid = spawn_resp.subagent_id
        subagent_ids.append(sid)

        await subagents.delegate(
            subagent_id=sid,
            task_name=t["task_name"],
            instruction=t["instruction"],
        )
        print(f"Started: {t['name']} ({sid})")

    # Await all results concurrently
    results = await asyncio.gather(*[
        subagents.await_result(sid) for sid in subagent_ids
    ])

    for r in results:
        status_emoji = "OK" if r.status == "COMPLETED" else "ERR"
        print(f"[{status_emoji}] {r.subagent_id}: {r.status}")

    return results
```

### 4. Isolation Scopes — Choosing Memory and Tool Scope

```python
async def run_with_isolation():
    # Shared memory: subagent sees and modifies parent's memory
    spawn_shared = await subagents.spawn(
        name="collaborator",
        model="gpt-4",
        system_prompt="You share memory with the parent agent.",
        # memory_scope defaults to "shared"
        # tool_scope defaults to "restricted"
    )

    # Isolated memory: subagent gets its own memory namespace
    spawn_isolated = await subagents.spawn(
        name="sandbox",
        model="gpt-4",
        system_prompt="You work in isolation with your own memory.",
        # Note: memory_scope and tool_scope are set via SubagentConfig
        # on the server side. The client passes them through the config.
    )

    # Snapshot memory: subagent gets a copy of parent memory at spawn time
    spawn_snapshot = await subagents.spawn(
        name="reviewer",
        model="claude-3.5-sonnet",
        system_prompt="You review based on the context known at spawn time.",
        # snapshot = copy-on-spawn, writes go to subagent's own namespace
    )

    print(f"Shared:  {spawn_shared.subagent_id}")
    print(f"Isolated: {spawn_isolated.subagent_id}")
    print(f"Snapshot: {spawn_snapshot.subagent_id}")
```

### 5. Inter-agent Messaging

Subagents can send messages to each other through the host. This enables collaborative workflows where agents share intermediate results.

```python
async def run_collaborative():
    # Spawn two subagents that will collaborate
    alice = await subagents.spawn(
        name="alice",
        model="claude-3.5-sonnet",
        role="analyst",
        system_prompt="You analyze data and send findings to Bob.",
    )
    bob = await subagents.spawn(
        name="bob",
        model="gpt-4",
        role="synthesizer",
        system_prompt="You receive analysis from Alice and produce a final report.",
    )

    # Delegate tasks
    await subagents.delegate(
        subagent_id=alice.subagent_id,
        task_name="analyze_data",
        instruction="Analyze the sales dataset and send key findings to Bob",
    )
    await subagents.delegate(
        subagent_id=bob.subagent_id,
        task_name="synthesize_report",
        instruction="Wait for Alice's analysis, then produce a final report",
    )

    # Await both
    alice_result = await subagents.await_result(alice.subagent_id)
    bob_result = await subagents.await_result(bob.subagent_id)

    print(f"Alice: {alice_result.status}")
    print(f"Bob:   {bob_result.status}")
```

### 6. Merging Results from Multiple Subagents

Use the merge protocol to combine results using different strategies.

```python
async def run_merge():
    # Spawn multiple reviewer subagents
    reviewer_ids = []
    for i in range(3):
        resp = await subagents.spawn(
            name=f"reviewer_{i}",
            model="claude-3.5-sonnet",
            role="review",
            system_prompt="You are a code reviewer. Assess the code quality.",
        )
        reviewer_ids.append(resp.subagent_id)

        await subagents.delegate(
            subagent_id=resp.subagent_id,
            task_name=f"review_{i}",
            instruction="Review the submitted code for bugs and style issues",
        )

    # Await all reviewers
    await asyncio.gather(*[
        subagents.await_result(sid) for sid in reviewer_ids
    ])

    # Merge with hierarchical summary (default)
    merge_resp = await subagents.merge(reviewer_ids, strategy="hierarchical_summary")
    print(f"Hierarchical merge:\n{merge_resp.merged_result}")

    # Or merge with voting (for agreement tasks)
    merge_resp = await subagents.merge(reviewer_ids, strategy="voting")
    print(f"Voting merge:\n{merge_resp.merged_result}")
```

Note: The `merge` method requires extending `SubagentClient` or sending `SubagentMergeRequest` directly through the transport. Here is the client extension:

```python
from a2e.caps.subagents.protocol import SubagentMergeRequest, SubagentMergeResponse

class ExtendedSubagentClient(SubagentClient):
    """Extended client with list, cancel, terminate, and merge support."""

    async def list_subagents(self):
        from a2e.caps.subagents.protocol import SubagentListRequest
        request = SubagentListRequest()
        return await self.transport.send(request)

    async def cancel(self, subagent_id: str):
        from a2e.caps.subagents.protocol import SubagentCancelRequest
        request = SubagentCancelRequest(subagent_id=subagent_id)
        return await self.transport.send(request)

    async def terminate(self, subagent_id: str):
        from a2e.caps.subagents.protocol import SubagentTerminateRequest
        request = SubagentTerminateRequest(subagent_id=subagent_id)
        return await self.transport.send(request)

    async def merge(
        self,
        subagent_ids: list[str],
        strategy: str = "hierarchical_summary",
    ) -> SubagentMergeResponse:
        request = SubagentMergeRequest(
            subagent_ids=subagent_ids,
            strategy=strategy,
        )
        return await self.transport.send(request)

    async def message(
        self,
        from_subagent_id: str,
        to_subagent_id: str,
        message_type: str,
        content: Any,
    ):
        from a2e.caps.subagents.protocol import SubagentMessageRequest, SubagentMessagePayload
        request = SubagentMessageRequest(
            from_subagent_id=from_subagent_id,
            to_subagent_id=to_subagent_id,
            message=SubagentMessagePayload(type=message_type, content=content),
        )
        return await self.transport.send(request)
```

### 7. Cancellation and Error Handling

```python
async def run_with_cancellation():
    # Spawn a long-running subagent
    resp = await subagents.spawn(
        name="long_task",
        model="gpt-4",
        system_prompt="You perform a lengthy analysis task.",
    )
    sid = resp.subagent_id

    await subagents.delegate(
        subagent_id=sid,
        task_name="deep_analysis",
        instruction="Perform a comprehensive analysis of the entire codebase",
    )

    # Cancel after deciding it's taking too long
    # Using the extended client:
    ext = ExtendedSubagentClient(client)
    await ext.cancel(sid)
    print(f"Cancelled: {sid}")

    # Or forcefully terminate (cancels + propagates to children)
    resp2 = await subagents.spawn(
        name="runaway",
        model="gpt-4",
        system_prompt="You are a subagent that might spawn more subagents.",
    )
    await subagents.delegate(
        subagent_id=resp2.subagent_id,
        task_name="recursive_task",
        instruction="Do something that may spawn child subagents",
    )
    await ext.terminate(resp2.subagent_id)
    print(f"Terminated: {resp2.subagent_id} (children also terminated)")
```

### 8. Full Orchestration Loop — Parent Agent Pattern

A realistic parent agent that uses subagents as part of its reasoning loop:

```python
from typing import Any

async def orchestration_loop(user_request: str) -> dict[str, Any]:
    """Parent agent pattern: decompose request, fan out to subagents, merge."""

    # Step 1: Decompose the user request into subtasks
    # (In practice, the LLM would do this decomposition)
    subtasks = [
        {
            "name": "planner",
            "model": "claude-3.5-sonnet",
            "task_name": "plan",
            "instruction": f"Create an execution plan for: {user_request}",
            "system_prompt": "You are a planning agent. Break tasks into steps.",
        },
    ]

    # Step 2: Run the planner
    planner_result = await subagents.run(
        name=subtasks[0]["name"],
        model=subtasks[0]["model"],
        task_name=subtasks[0]["task_name"],
        instruction=subtasks[0]["instruction"],
    )

    if planner_result.status != "COMPLETED":
        return {"error": "Planning failed", "detail": planner_result.error}

    # Step 3: Fan out execution subagents based on the plan
    # (Simplified: spawn 2 workers for parallel execution)
    worker_ids = []
    for i in range(2):
        resp = await subagents.spawn(
            name=f"worker_{i}",
            model="gpt-4",
            role="execution",
            system_prompt="You execute assigned tasks precisely and report results.",
            capabilities=["tools", "memory"],
        )
        worker_ids.append(resp.subagent_id)

        await subagents.delegate(
            subagent_id=resp.subagent_id,
            task_name=f"execute_part_{i}",
            instruction=f"Execute part {i} of the plan: {planner_result.result}",
        )

    # Step 4: Await all workers
    worker_results = await asyncio.gather(*[
        subagents.await_result(sid) for sid in worker_ids
    ])

    # Step 5: Check for failures
    failures = [r for r in worker_results if r.status != "COMPLETED"]
    if failures:
        for f in failures:
            print(f"Worker {f.subagent_id} failed: {f.error}")
        # Cancel remaining
        ext = ExtendedSubagentClient(client)
        for sid in worker_ids:
            await ext.cancel(sid)

    # Step 6: Merge results
    completed_ids = [
        r.subagent_id for r in worker_results if r.status == "COMPLETED"
    ]
    if completed_ids:
        ext = ExtendedSubagentClient(client)
        merged = await ext.merge(completed_ids, strategy="hierarchical_summary")
        return merged.merged_result

    return {"error": "All workers failed"}

client.disconnect()
```

## Key Patterns

| Pattern | Description | When to Use |
|---------|-------------|-------------|
| `spawn` → `delegate` → `await_result` | Manual 3-step orchestration | Need control between steps (check status, modify config) |
| `run()` | One-shot convenience | Simple single-subagent tasks |
| Fan-out / gather | Parallel subagents | Independent subtasks that don't need coordination |
| Inter-agent messaging | Collaborative subagents | Subagents that need to share intermediate results |
| Merge | Combine outputs | Multiple subagents producing related results |
| Cancel / Terminate | Stop runaway subagents | Timeout, error, or user abort scenarios |
| Depth-limited nesting | Recursive subagents | Complex tasks requiring hierarchical decomposition |

## Scope Selection Guide

| Scenario | memory_scope | tool_scope | Why |
|----------|-------------|------------|-----|
| Collaborative assistant | `shared` | `restricted` | Needs parent context, limited tool access |
| Independent researcher | `isolated` | `restricted` | No cross-contamination, safe tool subset |
| Snapshot reviewer | `snapshot` | `restricted` | Reads initial state, produces independent output |
| Trusted executor | `shared` | `shared` | Full parent access, trusted subagent |
| Sandboxed evaluator | `isolated` | `isolated` | Complete isolation for untrusted code |

## Tips

- **Set timeouts always**: Subagents can hang. Always configure `timeout_seconds` to prevent runaway tasks.
- **Use `max_steps`**: Limit agent loops within subagents to avoid infinite reasoning cycles.
- **Prefer `restricted` tool scope**: Only use `shared` when the subagent genuinely needs full tool access.
- **Cancel propagates**: When you terminate a subagent, all its children are also terminated. Use `cancel` for graceful, `terminate` for forced.
- **Batch await with `asyncio.gather`**: Waiting for multiple subagents sequentially is slow; always use gather.
- **Check status before delegating**: A subagent must be in `READY` status to accept a task. Re-spawn if it has already completed a task.
- **Use merge for consensus**: The `voting` strategy is ideal when multiple subagents should agree on an answer (e.g., code review, fact-checking).
- **Depth limit prevents infinite recursion**: The host enforces `max_depth` (default 3). Subagents cannot spawn subagents beyond this depth.
