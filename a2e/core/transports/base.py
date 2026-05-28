import pdb
from abc import ABC, abstractmethod
from typing import Callable, Optional


class BaseTransport(ABC):
    def __init__(self):
        self._handler: Optional[Callable[[str], None]] = None
        self._out_handler: Optional[Callable[[str], None]] = None

    @abstractmethod
    async def start(self):
        ...

    @abstractmethod
    async def send(self, msg: str):
        ...

    @abstractmethod
    async def deliver(self, msg: str):
        ...

    def set_message_handler(self, handler: Callable[[str], None]):
        self._handler = handler

    def set_out_handler(self, handler: Callable[[str], None]):
        self._out_handler = handler

    async def stop(self):
        ...
