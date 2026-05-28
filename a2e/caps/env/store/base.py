from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from a2e.caps.env.protocol import (
    _Episode,
)


class EpisodeStore(ABC):
    """
    Abstract persistence layer for environment episodes.
    """
    @abstractmethod
    def save(
        self,
        episode_id: str,
        env_name: str,
        episode: "_Episode"
    ) -> None:
        """Persist episode state"""
        pass

    @abstractmethod
    def load(
        self,
        episode_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Load episode state.

        Returns:
            {
                "env_name": str,
                "state": dict,
                "done": bool,
                "step_count": int,
                "created_at": float
            }
        """
        pass

    @abstractmethod
    def delete(self, episode_id: str) -> None:
        """Delete episode"""
        pass
