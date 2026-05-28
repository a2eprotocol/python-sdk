import time
import threading

from pydantic import BaseModel
from typing import Dict, Type, Optional, Any

from a2e.base import (
    A2EMessage,
    A2EError,
    A2EErrorCode
)
from a2e.core.plugins import (
    A2EPlugin
)
from a2e.caps.chains.protocol import (
    ChainRequest,
    ChainEvent,
    ChainResponse,
    MessageType
)


class ChainPlugin(A2EPlugin):
    name = "chain"
    priority = 10

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)

    # ---------------------------------------------------------
    # Supported Messages
    # ---------------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return {
            MessageType.CHAIN_REQ: ChainRequest,
        }

    # ---------------------------------------------------------
    # Entry Point
    # ---------------------------------------------------------
    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        response = None
        req_id = msg.id
        t0 = time.monotonic()

        if msg.type == MessageType.CHAIN_REQ:
            return self._run_chain(msg)

        # Return invalid message
        response = A2EError(**{
            "req_id": req_id,
            "code": A2EErrorCode.INVALID_MESSAGE,
            "message": f"Invalid message: {msg.type}",
            "retryable": False
        })
        self.audit_handle(msg, response, req_id, t0)
        return response

    # ---------------------------------------------------------
    # Core Execution
    # ---------------------------------------------------------
    def _run_chain(self, req: ChainRequest) -> ChainResponse:
        response = None
        t0 = time.monotonic()

        try:
            start_time = time.time()
            nodes = {
                n.id: n
                for n in req.nodes
            }

            outputs: Dict[str, Any] = {}
            completed = set()
            running = set()
            failed = set()
            lock = threading.Lock()
            seq = 0

            # -------------------------------------------------
            # Event Emitter
            # -------------------------------------------------
            def emit(
                node_id,
                phase,
                output=None,
                error="",
            ):
                nonlocal seq
                seq += 1

                self.host.send(
                    ChainEvent(
                        req_id=req.req_id,
                        node_id=node_id,
                        phase=phase,
                        output=output,
                        error=error,
                        seq=seq,
                    )
                )

            # -------------------------------------------------
            # Dependency Resolution
            # -------------------------------------------------
            def can_run(node):
                return all(
                    dep in completed
                    for dep in node.deps
                )

            def resolve_input(node):
                data = dict(
                    node.input or {}
                )

                for dep in node.deps:
                    data[dep] = outputs.get(dep)

                return data

            # -------------------------------------------------
            # Node Runner
            # -------------------------------------------------
            def run_node(node):
                emit(
                    node.id,
                    "start",
                )

                try:
                    inp = resolve_input(node)
                    if node.type == "tool":
                        result = self._run_tool(
                            node.name,
                            inp,
                        )
                    elif node.type == "proc":
                        result = self._run_proc(
                            node.name,
                            inp,
                        )
                    elif node.type == "skill":
                        result = self._run_skill(
                            node.name,
                            inp,
                        )
                    else:
                        raise Exception(
                            f"Unknown node type: "
                            f"{node.type}"
                        )

                    with lock:
                        outputs[node.id] = result
                        completed.add(node.id)
                        running.remove(node.id)

                    emit(
                        node.id,
                        "done",
                        output=result,
                    )
                except Exception as e:
                    with lock:
                        outputs[node.id] = None
                        completed.add(node.id)
                        failed.add(node.id)
                        running.remove(node.id)

                    emit(
                        node.id,
                        "error",
                        error=str(e),
                    )

            # -------------------------------------------------
            # Scheduler Loop
            # -------------------------------------------------
            threads = []
            while len(completed) < len(nodes):
                for node in nodes.values():
                    if (
                        node.id in completed
                        or node.id in running
                    ):
                        continue

                    if can_run(node):
                        running.add(node.id)

                        t = threading.Thread(
                            target=run_node,
                            args=(node,),
                            daemon=True,
                        )

                        t.start()
                        threads.append(t)

                time.sleep(0.01)

            for t in threads:
                t.join()

            duration_ms = int(
                (time.time() - start_time)
                * 1000
            )

            # -------------------------------------------------
            # Final Output
            # -------------------------------------------------
            terminal_nodes = [
                n.id
                for n in nodes.values()
                if not any(
                    n.id in x.deps
                    for x in nodes.values()
                )
            ]

            final_output = (
                outputs.get(
                    terminal_nodes[-1]
                )
                if terminal_nodes
                else None
            )

            response = ChainResponse(
                req_id=req.req_id,
                chain_id=req.chain_id,
                success=len(failed) == 0,
                outputs=outputs,
                final_output=final_output,
                duration_ms=duration_ms,
                nodes_run=len(completed),
            )
        except Exception as e:
            response = ChainResponse(
                req_id=req.req_id,
                chain_id=req.chain_id,
                success=False,
                outputs={},
                final_output=None,
                duration_ms=0,
                nodes_run=0,
                error=str(e),
            )
        finally:
            self.audit_handle(
                req,
                response,
                req.req_id,
                t0,
            )
            return response

    # ---------------------------------------------------------
    # Tool Execution
    # ---------------------------------------------------------
    def _run_tool(self, name: str, inp: dict):
        registry = getattr(self.host, "tool_registry", None)

        if not registry:
            raise Exception("ToolRegistry not available")

        tool = registry.get(name)
        if not tool:
            raise Exception(f"Tool not found: {name}")

        result = tool.runner(inp, lambda *_: None)

        if not result.success:
            raise Exception(result.error)

        return result.output

    # ---------------------------------------------------------
    # Proc Execution (blocking wrapper)
    # ---------------------------------------------------------
    def _run_proc(self, name: str, inp: dict):
        """
        Simple blocking wrapper over proc plugin.
        Assumes proc plugin exists on host.
        """
        proc_plugin = getattr(self.host, "get_plugin", lambda x: None)("proc")

        if not proc_plugin:
            raise Exception("ProcPlugin not available")

        # Spawn
        spawn_resp = proc_plugin._spawn(
            type("obj", (), {
                "req_id": "",
                "command": inp.get("command")
            })
        )

        proc_id = spawn_resp.proc_id

        # Wait for completion
        while True:
            status = proc_plugin._status(
                type("obj", (), {
                    "req_id": "",
                    "proc_id": proc_id
                })
            )

            if status.status in ("completed", "failed"):
                if status.status == "failed":
                    raise Exception(status.error)
                return {"status": status.status}

            time.sleep(0.05)
