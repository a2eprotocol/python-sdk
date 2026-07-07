"""
ChainPlugin — multi-step tool/skill/proc pipelines as a DAG (P5.E).

Reconciled with the current a2e chain protocol (ChainNode uses node_id /
kind / next_node / input_map / condition / true_node / false_node / items_path /
map_node / on_error). The earlier SDK plugin was written against an older
protocol (node.id / node.deps / node.type) and a host API that no longer
exists (host.tool_registry, host.get_plugin(...)._spawn). This rewrite:

  - parses req.nodes into ChainNode models,
  - resolves node inputs via input_map (JMESPath-lite: "$", "$.node_id",
    "$.node_id.field", or literal) over {initial_input + prior outputs},
  - runs tool / skill / proc nodes by calling the registered host plugin
    (self.host.get_plugin("tools"/"skill"/"proc").handle(...)),
  - supports branch (condition → true_node/false_node) and map (items_path →
    map_node fan-out) routing,
  - honours on_error (abort | skip | <node_id>) and timeout,
  - emits ChainEvent(start/done/error) per node when streaming,
  - returns a single ChainResponse with per-node outputs + final_output.

Node execution is synchronous inside handle(); the executor runs handle() on a
worker thread, so a chain blocks that thread until done (fine for agent-driven
pipelines).
"""
from __future__ import annotations

import time

from typing import Any, Dict, Optional

from a2e.caps.base.protocol import (
    A2EMessage,
    A2EError,
    A2EErrorCode,
)
from a2e.core.plugins import A2EPlugin
from a2e.caps.chains.protocol import (
    ChainNode,
    ChainRequest,
    ChainEvent,
    ChainResponse,
    ChainErrorCode,
    MessageType,
)


class ChainPlugin(A2EPlugin):
    name = "chain"
    priority = 10

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)

    # ────────────────────────────────────────────────────────────────
    # Supported Messages
    # ────────────────────────────────────────────────────────────────
    def supported_messages(self) -> Dict[str, type]:
        return {MessageType.CHAIN_REQ: ChainRequest}

    # ────────────────────────────────────────────────────────────────
    # Entry Point
    # ────────────────────────────────────────────────────────────────
    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        if msg.type == MessageType.CHAIN_REQ:
            return self._run_chain(msg)
        return A2EError(
            req_id=getattr(msg, "id", ""),
            code=A2EErrorCode.INVALID_MESSAGE,
            message=f"Invalid message: {msg.type}",
            retryable=False,
        )

    # ────────────────────────────────────────────────────────────────
    # Input / condition resolution (JMESPath-lite)
    # ────────────────────────────────────────────────────────────────
    @staticmethod
    def _resolve(expr: Any, ctx: dict) -> Any:
        if not isinstance(expr, str) or not expr.startswith("$"):
            return expr
        if expr == "$":
            return ctx
        path = expr[2:].split(".")
        cur: Any = ctx
        for part in path:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def _resolve_input(self, node: ChainNode, ctx: dict) -> dict:
        if node.input_map:
            out: dict = {}
            for k, v in node.input_map.items():
                out[k] = self._resolve(v, ctx)
            return out
        return dict(node.input or {})

    @staticmethod
    def _eval_condition(cond: str, ctx: dict) -> bool:
        cond = (cond or "").strip()
        if not cond:
            return True
        for op in ("==", "!=", ">=", "<=", ">", "<"):
            if op in cond:
                left, right = cond.split(op, 1)
                val = ChainPlugin._resolve(left.strip(), ctx)
                if isinstance(val, str):
                    val = val.strip()
                lit = right.strip()
                try:
                    lit_v: Any = int(lit)
                except ValueError:
                    try:
                        lit_v = float(lit)
                    except ValueError:
                        if lit in ("true", "false"):
                            lit_v = lit == "true"
                        else:
                            lit_v = lit.strip("'\"")
                if op == "==":
                    return val == lit_v
                if op == "!=":
                    return val != lit_v
                if val is None:
                    return False
                if op == ">":
                    return val > lit_v
                if op == "<":
                    return val < lit_v
                if op == ">=":
                    return val >= lit_v
                if op == "<=":
                    return val <= lit_v
        # bare path → truthiness
        return bool(ChainPlugin._resolve(cond, ctx))

    # ────────────────────────────────────────────────────────────────
    # Node execution (resolve via registered host plugins)
    # ────────────────────────────────────────────────────────────────
    # Map a node kind to the *name* of the host plugin that serves it.
    # self.plugins is keyed by plugin `name` (from host_config), not `type`.
    PLUGIN_FOR_KIND = {
        "tool": "xceed_terminal",
        "skill": "skills",
        "proc": "proc",
    }

    def _run_tool(self, name: str, inp: dict, session_id: str) -> Any:
        from a2e.caps.tools.protocol import ToolCallRequest

        plugin = self.host_instance.get_plugin(self.PLUGIN_FOR_KIND["tool"])
        if not plugin:
            raise RuntimeError("tools plugin not available")
        resp = plugin.handle(ToolCallRequest(
            tool_name=name, arguments=inp, session_id=session_id))
        data = getattr(resp, "data", None)
        if data is None or not getattr(data, "success", False):
            raise RuntimeError(getattr(data, "error", "tool failed"))
        return data.data

    def _run_skill(self, name: str, inp: dict, session_id: str) -> Any:
        from a2e.caps.skills.protocol import SkillCallRequest

        plugin = self.host_instance.get_plugin(self.PLUGIN_FOR_KIND["skill"])
        if not plugin:
            raise RuntimeError("skill plugin not available")
        resp = plugin.handle(SkillCallRequest(
            name=name, arguments=inp, correlation_id=session_id))
        data = getattr(resp, "data", None)
        if data is None or not getattr(data, "success", False):
            raise RuntimeError(getattr(data, "error", "skill failed"))
        return data.data

    def _run_proc(self, name: str, inp: dict, session_id: str,
                  timeout: int = 120) -> Any:
        from a2e.caps.proc.protocol import (
            ProcSpawnRequest, ProcStatusRequest, ProcKillRequest)

        plugin = self.host_instance.get_plugin(self.PLUGIN_FOR_KIND["proc"])
        if not plugin:
            raise RuntimeError("proc plugin not available")
        cmd = inp.get("command") or inp.get("cmd") or []
        if isinstance(cmd, str):
            cmd = cmd.split()
        spawn = plugin.handle(ProcSpawnRequest(
            cmd=cmd, timeout=timeout, session_id=session_id))
        proc_id = getattr(spawn, "proc_id", "")
        if not proc_id:
            raise RuntimeError(getattr(spawn, "error", "proc spawn failed"))
        deadline = time.time() + timeout
        status = "running"
        while time.time() < deadline:
            st = plugin.handle(ProcStatusRequest(proc_id=proc_id))
            status = getattr(st, "status", "running")
            if status != "running":
                break
            time.sleep(0.05)
        try:
            plugin.handle(ProcKillRequest(proc_id=proc_id))
        except Exception:
            pass
        return {"proc_id": proc_id, "status": status}

    def _run_node(self, node: ChainNode, inp: dict, session_id: str,
                  timeout: int) -> Any:
        if node.kind == "tool":
            return self._run_tool(node.name, inp, session_id)
        if node.kind == "skill":
            return self._run_skill(node.name, inp, session_id)
        if node.kind == "proc":
            return self._run_proc(node.name, inp, session_id, timeout)
        raise RuntimeError(f"Unknown node kind: {node.kind}")

    # ────────────────────────────────────────────────────────────────
    # Core execution
    # ────────────────────────────────────────────────────────────────
    def _run_chain(self, req: ChainRequest) -> ChainResponse:
        t0 = time.monotonic()
        try:
            nodes = {n.node_id: n for n in (ChainNode(**d) for d in req.nodes)}
            if not req.entry_node or req.entry_node not in nodes:
                return ChainResponse(
                    req_id=req.id, chain_id=req.chain_id, success=False,
                    error={"code": "bad_entry", "message": "entry_node missing"})

            outputs: Dict[str, Any] = {}
            visited: set[str] = set()
            failed: set[str] = set()
            emit = self._make_emitter(req)
            session_id = req.session_id
            deadline = time.time() + (req.timeout or 300)

            node_id = req.entry_node
            terminal = None
            while node_id:
                if node_id in visited:
                    return ChainResponse(
                        req_id=req.id, chain_id=req.chain_id, success=False,
                        error={"code": ChainErrorCode.CHAIN_CYCLE,
                               "message": f"cycle at {node_id}"})
                if time.time() > deadline:
                    return ChainResponse(
                        req_id=req.id, chain_id=req.chain_id, success=False,
                        error={"code": "timeout",
                               "message": "chain exceeded timeout"})
                visited.add(node_id)
                node = nodes[node_id]
                ctx = {**req.initial_input, **outputs}
                terminal = node_id

                # branch / map are routers, not executed directly
                if node.kind == "branch":
                    nxt = (node.true_node if self._eval_condition(
                        node.condition, ctx) else node.false_node)
                    node_id = nxt
                    continue
                if node.kind == "map":
                    items = self._resolve(node.items_path or "$", ctx)
                    items = items if isinstance(items, list) else [items]
                    res = []
                    for it in items:
                        ctx_item = {**ctx, "item": it}
                        emit(node.map_node, "start")
                        try:
                            out = self._run_node(
                                nodes[node.map_node], {"item": it}, session_id,
                                req.timeout)
                            outputs[node.map_node] = out
                            emit(node.map_node, "done", out)
                            res.append(out)
                        except Exception as e:
                            emit(node.map_node, "error", error=str(e))
                            failed.add(node.map_node)
                    outputs[node.node_id] = res
                    node_id = node.next_node
                    continue

                # regular executable node
                emit(node.node_id, "start")
                try:
                    inp = self._resolve_input(node, ctx)
                    out = self._run_node(node, inp, session_id, req.timeout)
                    outputs[node.node_id] = out
                    emit(node.node_id, "done", out)
                except Exception as e:
                    outputs[node.node_id] = None
                    failed.add(node.node_id)
                    emit(node.node_id, "error", error=str(e))
                    if node.on_error == "skip":
                        node_id = node.next_node
                        continue
                    if node.on_error and node.on_error not in ("abort", ""):
                        node_id = node.on_error
                        continue
                    return ChainResponse(
                        req_id=req.id, chain_id=req.chain_id, success=False,
                        outputs=outputs, final_output=None,
                        duration_ms=int((time.monotonic() - t0) * 1000),
                        nodes_run=len(outputs),
                        error={"code": ChainErrorCode.CHAIN_NODE_ERROR,
                               "message": str(e)})
                node_id = node.next_node

            resp = ChainResponse(
                req_id=req.id, chain_id=req.chain_id,
                success=len(failed) == 0,
                outputs=outputs,
                final_output=outputs.get(terminal),
                duration_ms=int((time.monotonic() - t0) * 1000),
                nodes_run=len(outputs),
            )
            self.audit_handle(req, resp, req.id, t0)
            return resp
        except Exception as e:
            resp = ChainResponse(
                req_id=req.id, chain_id=req.chain_id, success=False,
                outputs={}, final_output=None, duration_ms=0, nodes_run=0,
                error={"code": "chain_error", "message": str(e)})
            self.audit_handle(req, resp, req.id, t0)
            return resp

    def _make_emitter(self, req: ChainRequest):
        def emit(node_id, phase, output=None, error=""):
            if not req.streaming:
                return
            try:
                self.emit_event(ChainEvent(
                    req_id=req.id, node_id=node_id,
                    phase=phase, output=output, error=error))
            except Exception:
                pass
        return emit
