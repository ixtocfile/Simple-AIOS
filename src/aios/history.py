"""Persist task lifecycle only, using the standard-library SQLite driver."""

from datetime import UTC, datetime
from pathlib import Path
import re
import sqlite3


# Mask the whole task before writing it, including to SQLite's journal.
# This conservative heuristic cannot identify every possible secret.
_SENSITIVE_TASK = re.compile(
    r"\b(?:password|passwd|passphrase|token|secret|api[_ -]?key|"
    r"private[_ -]?key|mot\s+de\s+passe|cl[ée]\s+(?:api|priv[ée]e|secr[èe]te))\b"
    r"|://[^\s/]*:[^\s/]*@"
    r"|-----BEGIN [^-]*PRIVATE KEY-----"
    r"|\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{16,}",
    re.IGNORECASE,
)
REDACTED_TASK = "[contenu sensible masqué]"


class TaskHistory:
    """Own one connection; callers must close it when the CLI session ends."""

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = data_dir / "history.sqlite3"
        path.touch(mode=0o600, exist_ok=True)
        self._connection = sqlite3.connect(path)
        try:
            with self._connection:
                self._connection.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY,
                        task TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (
                            status IN ('running', 'completed', 'failed', 'interrupted')
                        )
                    )
                """)
        except BaseException:
            self.close()
            raise

    def start(self, task: str) -> int:
        """Commit a running task before any provider call or tool execution."""
        if not isinstance(task, str) or not task.strip():
            raise ValueError("Task must be a non-empty string")
        safe_task = REDACTED_TASK if _SENSITIVE_TASK.search(task) else task.strip()
        timestamp = datetime.now(UTC).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO tasks (task, timestamp, status) VALUES (?, ?, 'running')",
                (safe_task, timestamp),
            )
        return cursor.lastrowid

    def finish(self, task_id: int, status: str) -> None:
        """Finalize this task without changing its text or start timestamp."""
        if type(task_id) is not int or task_id < 1:
            raise ValueError("Invalid task ID")
        if status not in ("completed", "failed", "interrupted"):
            raise ValueError("Invalid final task status")
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE tasks SET status = ? WHERE id = ? AND status = 'running'",
                (status, task_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Unknown or already finished task")

    def close(self) -> None:
        self._connection.close()
