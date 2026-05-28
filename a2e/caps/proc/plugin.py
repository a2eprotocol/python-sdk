# ---------------------------------------------------------------------------
# BASE PROC PLUGIN
# ---------------------------------------------------------------------------
import pdb
import uuid
import json
import time
import threading
import subprocess
from pydantic import BaseModel
from typing import Dict, Type, Optional

from a2e.caps.base import (
    A2EMessage,
    A2EError,
    A2EErrorCode
)

from a2e.core.plugins import (
    A2EPlugin
)
from a2e.caps.proc.protocol import (
    MessageType,
    ProcSpawnRequest,
    ProcSpawnResponse,
    ProcWriteRequest,
    ProcWriteResponse,
    ProcReadEvent,
    ProcKillRequest,
    ProcKillResponse,
    ProcStatusRequest,
    ProcStatusResponse,
)


ALLOWED_COMMANDS = {"python3", "bash", "ls"}


class ProcSession:
    def __init__(self, proc_id: str, process: subprocess.Popen, req_id=None):
        self.proc_id = proc_id
        self.process = process
        self.req_id = req_id
        self.status = "running"
        self.error: str | None = None


class ProcPlugin(A2EPlugin):
    name = "proc"
    priority = 5

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)
        self.sessions: Dict[str, ProcSession] = {}

        self.allowed_commands = config.get(
            "ALLOWED_COMMANDS", ALLOWED_COMMANDS
        )

    # ---------------------------------------------------------
    # Supported messages
    # ---------------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return {
            MessageType.PROC_SPAWN_REQ: ProcSpawnRequest,
            MessageType.PROC_WRITE_REQ: ProcWriteRequest,
            MessageType.PROC_KILL_REQ: ProcKillRequest,
            MessageType.PROC_STATUS_REQ: ProcStatusRequest,
        }

    # ---------------------------------------------------------
    # Dispatcher
    # ---------------------------------------------------------
    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        response = None
        req_id = msg.id
        t0 = time.monotonic()
        t = msg.type

        if t == MessageType.PROC_SPAWN_REQ:
            return self._spawn(msg)

        if t == MessageType.PROC_WRITE_REQ:
            return self._write(msg)

        if t == MessageType.PROC_STATUS_REQ:
            return self._status(msg)

        if t == MessageType.PROC_KILL_REQ:
            return self._kill(msg)

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
    # Spawn (Shell Process)
    # ---------------------------------------------------------
    def _spawn(self, msg: ProcSpawnRequest):
        proc_id = uuid.uuid4().hex
        response = None
        t0 = time.monotonic()

        # ─────────────────────────────
        # Validate Command Type
        # ─────────────────────────────

        if not isinstance(msg.cmd, list):
            response = ProcSpawnResponse(
                req_id=msg.id,
                proc_id="",
                ok=False,
                pid=None,
                error="Command must be a list",
            )

            self.audit_handle(
                msg,
                response,
                msg.id,
                t0,
            )
            return response

        # ─────────────────────────────
        # Validate Command Allowlist
        # ─────────────────────────────

        if not msg.cmd:
            response = ProcSpawnResponse(
                req_id=msg.id,
                proc_id="",
                ok=False,
                pid=None,
                error="Empty command",
            )
            self.audit_handle(
                msg,
                response,
                msg.id,
                t0,
            )
            return response

        if msg.cmd[0] not in self.allowed_commands:
            response = ProcSpawnResponse(
                req_id=msg.id,
                proc_id="",
                ok=False,
                pid=None,
                error="Command not allowed",
            )
            self.audit_handle(
                msg,
                response,
                msg.id,
                t0,
            )
            return response

        # ─────────────────────────────
        # Spawn Process
        # ─────────────────────────────
        try:
            process = subprocess.Popen(
                msg.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                shell=False,
            )

            session = ProcSession(
                proc_id,
                process,
                msg.id,
            )

            self.sessions[proc_id] = session

            threading.Thread(
                target=self._stream_output,
                args=(
                    session,
                    process.stdout,
                    "stdout",
                ),
                daemon=True,
            ).start()

            threading.Thread(
                target=self._stream_output,
                args=(
                    session,
                    process.stderr,
                    "stderr",
                ),
                daemon=True,
            ).start()

            threading.Thread(
                target=self._wait_process,
                args=(session,),
                daemon=True,
            ).start()

            response = ProcSpawnResponse(
                req_id=msg.id,
                proc_id=proc_id,
                pid=process.pid,
                ok=True,
                error="",
            )

        except Exception as error:
            response = ProcSpawnResponse(
                req_id=msg.id,
                proc_id="",
                ok=False,
                pid=None,
                error=str(error),
            )
        finally:
            self.audit_handle(
                msg,
                response,
                msg.id,
                t0,
            )
            return response

    # ---------------------------------------------------------
    # Stream output → PROC_READ_EVENT
    # ---------------------------------------------------------
    def _stream_output(
        self,
        session: ProcSession,
        stream, stream_type: str
    ):
        for line in iter(stream.readline, ""):
            self._emit_event(
                proc_id=session.proc_id,
                stream_type=stream_type,
                data={"text": line},
                req_id=session.req_id
            )

    def _wait_process(self, session: ProcSession):
        proc = session.process
        proc.wait()

        if session.status == "killed":
            return

        if proc.returncode == 0:
            session.status = "completed"
            self._emit_event(
                proc_id=session.proc_id,
                stream_type="stdout",
                data={"code": 0},
                req_id=session.req_id
            )
        else:
            session.status = "failed"
            session.error = f"exit code {proc.returncode}"
            self._emit_event(
                proc_id=session.proc_id,
                stream_type="stderr",
                data={"code": proc.returncode},
                req_id=session.req_id
            )

    # ---------------------------------------------------------
    # Write → stdin
    # ---------------------------------------------------------
    def _write(self, msg: ProcWriteRequest):
        response = None
        t0 = time.monotonic()

        try:
            session = self.sessions.get(
                msg.proc_id
            )

            if not session:
                response = ProcWriteResponse(
                    req_id=msg.id,
                    proc_id=msg.proc_id,
                    success=False,
                    error="session not found",
                )
                return response

            proc = session.process
            if not proc.stdin:
                response = ProcWriteResponse(
                    req_id=msg.id,
                    proc_id=msg.proc_id,
                    success=False,
                    error="stdin not available",
                )
                return response

            proc.stdin.write(msg.data)
            proc.stdin.flush()

            response = ProcWriteResponse(
                req_id=msg.id,
                proc_id=msg.proc_id,
                success=True,
                error="",
            )
        except Exception as e:
            if session:
                session.error = str(e)
                session.status = "failed"

            response = ProcWriteResponse(
                req_id=msg.id,
                proc_id=msg.proc_id,
                success=False,
                error=str(e),
            )
        finally:
            self.audit_handle(
                msg,
                response,
                msg.id,
                t0,
            )
            return response

    # ---------------------------------------------------------
    # Status
    # ---------------------------------------------------------
    def _status(self, msg: ProcStatusRequest):
        response = None
        t0 = time.monotonic()

        try:
            session = self.sessions.get(
                msg.proc_id
            )

            if not session:
                response = ProcStatusResponse(
                    req_id=msg.id,
                    proc_id=msg.proc_id,
                    status="not_found",
                    error="session not found",
                )
                return response

            response = ProcStatusResponse(
                req_id=msg.id,
                proc_id=msg.proc_id,
                status=session.status,
                error=session.error or "",
            )
        except Exception as e:
            response = ProcStatusResponse(
                req_id=msg.id,
                proc_id=msg.proc_id,
                status="error",
                error=str(e),
            )
        finally:
            self.audit_handle(
                msg,
                response,
                msg.id,
                t0,
            )
            return response

    # ---------------------------------------------------------
    # Kill
    # ---------------------------------------------------------
    def _kill(self, msg: ProcKillRequest):
        response = None
        t0 = time.monotonic()

        try:
            session = self.sessions.get(
                msg.proc_id
            )

            if not session:
                response = ProcKillResponse(
                    req_id=msg.id,
                    success=False,
                )
                return response

            session.process.terminate()
            session.status = "killed"
            self._emit_event(
                msg.proc_id,
                "killed",
                {},
            )

            response = ProcKillResponse(
                req_id=msg.id,
                success=True,
            )
        except Exception as e:
            if session:
                session.error = str(e)
                session.status = "failed"

            response = ProcKillResponse(
                req_id=msg.id,
                success=False,
            )
        finally:
            self.audit_handle(
                msg,
                response,
                msg.id,
                t0,
            )
            return response

    # ---------------------------------------------------------
    # Emit helper
    # ---------------------------------------------------------
    def _emit_event(
        self, proc_id: str, stream_type: str, data: dict, req_id: str
    ):
        try:
            event = ProcReadEvent(
                proc_id=proc_id,
                stream_type=stream_type,
                data=json.dumps(data),
                req_id=req_id
            )
            self.host_instance._send(event)
        except Exception as error:
            print(f"failed to send event: {str(error)}")
            pass
