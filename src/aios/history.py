"""Persist task and tool lifecycles using the standard-library SQLite driver."""

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3

from aios.tools import ToolResult


# Mask the whole task before writing it, including to SQLite's journal.
# This conservative heuristic cannot identify every possible secret.
_SENSITIVE_TASK = re.compile(
    r"\b(?:password|passwd|passphrase|token|secret|api[_ -]?key|"
    r"private[_ -]?key|mot\s+de\s+passe|cl[ée]\s+(?:api|priv[ée]e|secr[èe]te))\b"
    r"|://[^\s/]*:[^\s/]*@"
    r"|-----BEGIN [^-]*PRIVATE KEY-----"
    r"|\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=._-]+"
    r"|\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{16,}",
    re.IGNORECASE,
)
REDACTED_TASK = "[contenu sensible masqué]"


def _safe_json(value: object) -> str:
    """Copy JSON data and mask sensitive fields before any database write."""
    def redact(item):
        if isinstance(item, dict):
            clean = {}
            for key, child in item.items():
                # Normalize snake_case, kebab-case and camelCase credential keys.
                normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
                sensitive = _SENSITIVE_TASK.search(key) or any(marker in normalized for marker in (
                    "password", "passwd", "passphrase", "pwd", "token", "secret",
                    "credential", "authorization", "cookie", "apikey",
                    "accesskey", "privatekey", "motdepasse",
                ))
                safe_key = REDACTED_TASK if sensitive else key
                clean[safe_key] = REDACTED_TASK if sensitive else redact(child)
            return clean
        if isinstance(item, list):
            return [redact(child) for child in item]
        if isinstance(item, str) and _SENSITIVE_TASK.search(item):
            return REDACTED_TASK
        return item

    copied = json.loads(json.dumps(value, allow_nan=False))
    return json.dumps(redact(copied), allow_nan=False)


class TaskHistory:
    """Own one connection; callers must close it when the CLI session ends."""

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = data_dir / "history.sqlite3"
        path.touch(mode=0o600, exist_ok=True)
        self._connection = sqlite3.connect(path)
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
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
                self._connection.execute("""
                    CREATE TABLE IF NOT EXISTS tool_calls (
                        id INTEGER PRIMARY KEY,
                        task_id INTEGER NOT NULL REFERENCES tasks(id),
                        tool TEXT,
                        arguments TEXT,
                        timestamp TEXT NOT NULL,
                        result TEXT,
                        status TEXT NOT NULL CHECK (
                            status IN ('running', 'succeeded', 'failed', 'interrupted')
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

    def start_tool(
        self, task_id: int, tool: str | None, arguments: dict[str, object] | None,
    ) -> int:
        """Commit an attempt before validation, authorization or execution."""
        if type(task_id) is not int or task_id < 1:
            raise ValueError("Invalid task ID")
        if tool is not None and (not isinstance(tool, str) or not tool.strip()):
            raise ValueError("Invalid tool name")
        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("Invalid tool arguments")
        safe_tool = REDACTED_TASK if tool and _SENSITIVE_TASK.search(tool) else tool
        safe_arguments = _safe_json(arguments) if arguments is not None else None
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO tool_calls (task_id, tool, arguments, timestamp, status) "
                "SELECT id, ?, ?, ?, 'running' FROM tasks WHERE id = ? AND status = 'running'",
                (safe_tool, safe_arguments, datetime.now(UTC).isoformat(), task_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Unknown or finished task")
        return cursor.lastrowid

    def finish_tool(self, call_id: int, result: ToolResult | None) -> None:
        """Save the outcome; None marks an interruption with an unknown outcome."""
        if type(call_id) is not int or call_id < 1:
            raise ValueError("Invalid tool call ID")
        if result is not None and not isinstance(result, ToolResult):
            raise TypeError("Invalid tool result")
        status = "interrupted"
        if result is not None:
            status = "succeeded" if result.success else "failed"
        safe_result = None if result is None else _safe_json(asdict(result))
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE tool_calls SET result = ?, status = ? WHERE id = ? AND status = 'running'",
                (safe_result, status, call_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Unknown or already finished tool call")

    def close(self) -> None:
        self._connection.close()
