import pdb
from typing import List, Dict, Any, Callable, Optional

from a2e.core.client import A2EClient
from a2e.caps.proc import (
    PROC_TYPE_MAP,
    ProcSpawnRequest,
    ProcSpawnResponse,
    ProcKillRequest,
    ProcKillResponse,
    ProcStatusRequest,
    ProcStatusResponse,
    ProcReadEvent,
    ProcWriteRequest
)


ProcReadCallback = Callable[[ProcReadEvent], None]


class ProcsAPI:
    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(PROC_TYPE_MAP)
        self._proc_callbacks: Dict[str, ProcReadCallback] = {}

    def spawn(
        self,
        cmd: List[str],
        cwd: str = "",
        env: dict = None,
        stdin_mode: str = "pipe",
        timeout: int = 100000,
        on_output: Optional[ProcReadCallback] = None,
    ) -> ProcSpawnResponse:
        req = ProcSpawnRequest(
            session_id=self._c._session_id,
            cmd=cmd,
            cwd=cwd,
            env=env or {},
            stdin_mode=stdin_mode,
            timeout=timeout,
        )
        resp = self._c.rpc(req, timeout=timeout, event_callback=on_output)
        if not isinstance(resp, ProcSpawnResponse):
            raise ConnectionError(f"Unexpected proc response: {type(resp)}")

        if resp.ok and on_output:
            self._proc_callbacks[resp.proc_id] = on_output
        return resp

    def write(
        self,
        proc_id: str,
        data: str,
        eof: bool = False
    ):
        resp = self._c._send(
            ProcWriteRequest(
                proc_id=proc_id,
                data=data,
                eof=eof
            )
        )
        return resp

    def kill(
        self,
        proc_id: str,
        signal: str = "SIGTERM",
        timeout: int = 10
    ) -> ProcKillResponse:
        req = ProcKillRequest(proc_id=proc_id, signal=signal)
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, ProcKillResponse):
            raise ConnectionError(f"Unexpected kill response: {type(resp)}")
        return resp

    def status(
        self,
        proc_id: str = "",
        timeout: int = 5
    ) -> List[Dict[str, Any]]:
        req = ProcStatusRequest(proc_id=proc_id)
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, ProcStatusResponse):
            raise ConnectionError(f"Unexpected status response: {type(resp)}")
        return resp
