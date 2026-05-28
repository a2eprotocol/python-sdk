# ---------------------------------------------------------------------------
# SQLITE STORE (DEFAULT IMPLEMENTATION)
# ---------------------------------------------------------------------------
import sqlite3
import json
import time
from a2e.caps.env.store.base import EpisodeStore
from a2e.caps.env.protocol import _Episode
from typing import Optional, Dict, Any


class SQLiteEpisodeStore(EpisodeStore):

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            episode_id TEXT PRIMARY KEY,
            env_name   TEXT,
            state      TEXT,
            done       INTEGER,
            step_count INTEGER,
            created_at REAL,
            updated_at REAL
        )
        """)
        self.conn.commit()

    # ---------------------------------------------------------------------

    def save(self, episode_id: str, env_name: str, episode: "_Episode") -> None:
        self.conn.execute("""
        INSERT OR REPLACE INTO episodes
        (episode_id, env_name, state, done, step_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            episode_id,
            env_name,
            json.dumps(episode.state),
            int(episode.done),
            episode.step_count,
            episode.created_at,
            time.time()
        ))
        self.conn.commit()

    # ---------------------------------------------------------------------

    def load(self, episode_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("""
        SELECT env_name, state, done, step_count, created_at
        FROM episodes WHERE episode_id = ?
        """, (episode_id,))
        row = cur.fetchone()

        if not row:
            return None

        env_name, state, done, step_count, created_at = row

        return {
            "env_name": env_name,
            "state": json.loads(state),
            "done": bool(done),
            "step_count": step_count,
            "created_at": created_at
        }

    # ---------------------------------------------------------------------

    def delete(self, episode_id: str) -> None:
        self.conn.execute("DELETE FROM episodes WHERE episode_id = ?", (episode_id,))
        self.conn.commit()
