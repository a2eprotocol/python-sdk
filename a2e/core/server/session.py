import uuid
import asyncio
from a2e.core.server.executor import A2EServerRuntimeExecutor


class Session:
    def __init__(
        self,
        config,
        transport,
        logger
    ):
        self.id = uuid.uuid4().hex
        self._logger = logger
        self.transport = transport
        self.outbound = asyncio.Queue()

        self.executor = A2EServerRuntimeExecutor(   # <- separate runtime loop
            config=config,
            transport=transport,
            logger=logger,
        )

        self.transport.set_message_handler(self.executor.handle_raw)
        self.executor.start()

    def bind_transport(self):
        def handler(msg: str):
            try:
                self.outbound.put_nowait(msg)
            except Exception:
                self._logger.exception("[stream] queue push failed")

        self.transport.set_out_handler(handler)

    async def stream(self):
        while True:
            msg = await self.outbound.get()
            yield msg
