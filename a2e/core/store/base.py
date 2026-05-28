from abc import ABC, abstractmethod
from typing import Dict, Any


class SnapshotStore(ABC):

    @abstractmethod
    def save(self, key: str, state: Dict[str, Any]):
        pass

    @abstractmethod
    def load(self, key: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def delete(self, key: str):
        pass
