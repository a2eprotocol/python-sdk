import sqlite3
import json
from a2e.core.store.base import (
    SnapshotStore
)


class SQLiteSnapshotStore(SnapshotStore):

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                key TEXT PRIMARY KEY,
                state TEXT
            )
        """)

    def save(self, key: str, state: dict):
        self.conn.execute(
            "REPLACE INTO snapshots (key, state) VALUES (?, ?)",
            (key, json.dumps(state))
        )
        self.conn.commit()

    def load(self, key: str) -> dict:
        cur = self.conn.execute(
            "SELECT state FROM snapshots WHERE key=?",
            (key,)
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(key)
        return json.loads(row[0])

    def delete(self, key: str):
        self.conn.execute("DELETE FROM snapshots WHERE key=?", (key,))
        self.conn.commit()
