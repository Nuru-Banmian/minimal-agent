import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import BinaryIO

from minimal_agent.client import Message


class SessionError(Exception):
    """A session could not be opened, read, or committed safely."""


class SessionStore:
    """Keep complete turns in order; identity comes only from the application."""

    def __init__(self, path: str | Path, user_id: str, session_id: str) -> None:
        if not user_id.strip() or not session_id.strip():
            raise SessionError("user_id 和 session_id 不能为空。")
        self.identity = (user_id, session_id)
        self._lock: BinaryIO | None = None
        self._closed = False
        try:
            if str(path) != ":memory:":
                database = Path(path).resolve()
                lock_dir = database.with_name(database.name + ".locks")
                lock_dir.mkdir(exist_ok=True)
                key = hashlib.sha256(json.dumps(self.identity).encode()).hexdigest()
                self._lock = (lock_dir / key).open("a+b")
                # Never unlink lock files: existing waiters must share the same inode.
                self._lock.seek(0, os.SEEK_END)
                if self._lock.tell() == 0:
                    self._lock.write(b"\0")
                    self._lock.flush()
                self._lock.seek(0)
                try:
                    if sys.platform == "win32":
                        import msvcrt

                        msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    raise SessionError("该 session 已被其他运行者占用，请先退出原终端。") from error
                path = database
            self.connection = sqlite3.connect(path, timeout=5)
        except BaseException:
            if self._lock is not None:
                self._lock.close()
            raise
        try:
            with self.connection:
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS messages ("
                    "user_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                    "sequence INTEGER NOT NULL, payload TEXT NOT NULL, "
                    "PRIMARY KEY (user_id, session_id, sequence))"
                )
        except BaseException:
            self.close()
            raise

    def read(self) -> list[Message]:
        if self._closed:
            raise SessionError("会话已关闭，请重新打开。")
        rows = self.connection.execute(
            "SELECT payload FROM messages WHERE user_id = ? AND session_id = ? ORDER BY sequence",
            self.identity,
        )
        return [json.loads(row[0]) for row in rows]

    def append(self, messages: list[Message]) -> None:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            last = self.connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM messages "
                "WHERE user_id = ? AND session_id = ?",
                self.identity,
            ).fetchone()[0]
            self.connection.executemany(
                "INSERT INTO messages VALUES (?, ?, ?, ?)",
                [
                    (*self.identity, last + offset, json.dumps(message, ensure_ascii=False))
                    for offset, message in enumerate(messages, 1)
                ],
            )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self.connection.close()
            finally:
                if self._lock is not None:
                    self._lock.close()
