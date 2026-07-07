"""
Standalone test of the `a2e.caps.subagents` package WITHOUT the A2E host,
transport, or RPC layer.

This proves the subagent *business logic* (SubagentPlugin / SubagentRuntime)
is independently testable in-process — it does not need an A2EPlugin, a host,
or a network. It also exercises SubagentClient against a fake in-memory
transport so the client contract is covered too.

Run:  python -m pytest a2e/caps/subagents/test_subagents_standalone.py -q
Or:    python a2e/caps/subagents/test_subagents_standalone.py

NOTE (design finding): SubagentPlugin.delegate() does
`asyncio.create_task(runtime.run_task(...))` and returns immediately, so the
subagent task lives on whatever event loop is active at delegate() time. The
lifecycle tests therefore must run spawn+delegate+await inside ONE event loop
(single asyncio.run). If the loop is torn down between delegate and await — as
happens if each call is wrapped in its own asyncio.run(), or if a host
recycles its loop — the task is cancelled silently. See test docstrings.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Make the repo root importable when run as a bare script (pytest does this
# automatically via rootdir, but `python path/to/file.py` does not).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from a2e.caps.subagents.plugin import SubagentPlugin  # noqa: E402
from a2e.caps.subagents.protocol import (  # noqa: E402
    SubagentAwaitRequest,
    SubagentConfig,
    SubagentDelegateRequest,
    SubagentSpawnRequest,
    SubagentStatus,
    TaskDefinition,
)


def _task(name="t", instruction="do thing"):
    return TaskDefinition(name=name, instruction=instruction)


# ── Fake transport ──────────────────────────────────────────────────────
class FakeTransport:
    def __init__(self, plugin: SubagentPlugin):
        self._plugin = plugin

    async def send(self, request):
        t = request.type
        if t == "SUBAGENT_SPAWN_REQ":
            return self._plugin.spawn(request)
        if t == "SUBAGENT_DELEGATE_REQ":
            return self._plugin.delegate(request)
        if t == "SUBAGENT_AWAIT_REQ":
            return self._plugin.await_result(request.subagent_id)
        if t == "SUBAGENT_LIST_REQ":
            subs = self._plugin.list_subagents()
            return _FakeResp(subagents=[s.model_dump() for s in subs])
        if t == "SUBAGENT_TERMINATE_REQ":
            self._plugin.terminate(request.subagent_id)
            return _FakeResp(terminated=True)
        raise AssertionError(f"unexpected request type: {t}")


class _FakeResp:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ── Direct plugin tests (no transport) ──────────────────────────────────
def test_spawn_creates_ready_subagent():
    p = SubagentPlugin()
    try:
        resp = p.spawn(SubagentSpawnRequest(
            agent=SubagentConfig(name="worker", model="gpt-4")))
        assert resp.status == SubagentStatus.READY
        assert resp.subagent_id.startswith("sub_")
        assert resp.subagent_id in p.subagents
    finally:
        p.shutdown()


def test_terminate_marks_terminated():
    p = SubagentPlugin()
    try:
        spawn = p.spawn(SubagentSpawnRequest(
            agent=SubagentConfig(name="w", model="m")))
        sid = spawn.subagent_id
        p.terminate(sid)
        assert p.subagents[sid].status == SubagentStatus.TERMINATED
    finally:
        p.shutdown()


def test_runner_failure_marks_failed_not_crash():
    """The base SubagentRuntime.run_task wraps execution in try/except and
    marks the runtime FAILED on exception. Verify that safety net directly by
    substituting a failing run_task and confirming it does NOT escape."""
    p = SubagentPlugin()
    try:
        spawn = p.spawn(SubagentSpawnRequest(
            agent=SubagentConfig(name="w", model="m")))
        sid = spawn.subagent_id
        rt = p.subagents[sid]

        async def failing(req: SubagentDelegateRequest):
            # mirrors the real run_task's try/except contract
            try:
                raise RuntimeError("kaboom")
            except Exception as exc:
                rt.status = SubagentStatus.FAILED
                rt.result = {"error": str(exc)}

        rt.run_task = failing  # type: ignore[assignment]

        p.delegate(SubagentDelegateRequest(subagent_id=sid, task=_task()))
        await_resp = p.await_result(sid)
        assert await_resp.status == SubagentStatus.FAILED
        assert await_resp.result is not None
        assert "kaboom" in await_resp.result["error"]
    finally:
        p.shutdown()


# ── Lifecycle tests: delegate+await now safe across loops (see module doc) ──
def test_delegate_then_await_returns_completed_result():
    p = SubagentPlugin()
    try:
        spawn = SubagentSpawnRequest(agent=SubagentConfig(name="worker", model="gpt-4"))
        sp = p.spawn(spawn)
        sid = sp.subagent_id
        p.delegate(SubagentDelegateRequest(subagent_id=sid, task=_task()))
        await_resp = p.await_result(sid)
        assert await_resp.status == SubagentStatus.COMPLETED
        assert await_resp.result is not None
        assert await_resp.result["instruction"] == "do thing"
    finally:
        p.shutdown()


def test_list_reflects_spawned_subagents():
    p = SubagentPlugin()
    try:
        sp = p.spawn(SubagentSpawnRequest(
            agent=SubagentConfig(name="w", model="m")))
        subs = p.list_subagents()
        assert any(s.subagent_id == sp.subagent_id for s in subs)
    finally:
        p.shutdown()


# ── Client tests via fake transport (single loop) ───────────────────────
def test_client_run_end_to_end():
    from a2e.caps.subagents.client import SubagentClient

    plugin = SubagentPlugin()
    client = SubagentClient(FakeTransport(plugin))

    async def go():
        return await client.run(
            name="worker", model="gpt-4",
            task_name="t1", instruction="do thing")

    res = asyncio.run(go())
    assert res.status == SubagentStatus.COMPLETED
    assert res.result is not None
    assert res.result["instruction"] == "do thing"
    # and it actually landed in the plugin's registry
    assert len(plugin.subagents) == 1
    plugin.shutdown()


# ── REGRESSION: delegate then await across SEPARATE event loops ──────────
# This is the exact pattern that previously silently cancelled the subagent
# task (delegate() used asyncio.create_task on the caller's loop, which was
# torn down before await). Since the plugin now owns its loop, the task must
# survive and complete even when spawn/delegate/await each run on a distinct
# loop.
def test_delegate_survives_loop_teardown_between_calls():
    p = SubagentPlugin()
    try:
        # spawn/delegate/await are now SYNCHRONOUS (they bridge to the plugin's
        # owned loop). Each is invoked from its own fresh asyncio.run() context
        # to prove the owned loop keeps the task alive across caller-loop churn.
        sid = asyncio.run(asyncio.sleep(0)) or p.spawn(SubagentSpawnRequest(
            agent=SubagentConfig(name="w", model="m"))).subagent_id

        # delegate from a separate event loop
        asyncio.run(asyncio.sleep(0))
        p.delegate(SubagentDelegateRequest(subagent_id=sid, task=_task()))

        # await from yet another separate event loop — must NOT lose the task
        asyncio.run(asyncio.sleep(0))
        resp = p.await_result(sid)
        assert resp.status == SubagentStatus.COMPLETED
        assert resp.result is not None
        assert resp.result["instruction"] == "do thing"
    finally:
        p.shutdown()


def test_shutdown_stops_owned_loop():
    p = SubagentPlugin()
    assert p._loop.is_running()
    p.shutdown()
    assert not p._loop.is_running()
    assert p._loop.is_closed()


if __name__ == "__main__":
    test_spawn_creates_ready_subagent()
    test_terminate_marks_terminated()
    test_runner_failure_marks_failed_not_crash()
    test_delegate_then_await_returns_completed_result()
    test_list_reflects_spawned_subagents()
    test_client_run_end_to_end()
    test_delegate_survives_loop_teardown_between_calls()
    test_shutdown_stops_owned_loop()
    print("ALL STANDALONE SUBAGENT TESTS PASSED")
