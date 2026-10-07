"""Conversation and tool orchestration, independent of terminal input/output."""

from collections.abc import Callable
from dataclasses import asdict
import json
from pathlib import Path

from aios._filesystem import normalize_filesystem_roots
from aios.filesystem_list import FilesystemListTool
from aios.filesystem_mkdir import FilesystemMkdirTool
from aios.filesystem_read import FilesystemReadTool
from aios.filesystem_update import FilesystemUpdateTool
from aios.filesystem_write import FilesystemWriteTool
from aios.history import TaskHistory
from aios.llm import LLMProvider, Message
from aios.policy import PolicyDecision, PolicyEngine
from aios.process_list import ProcessListTool
from aios.system_disk import SystemDiskTool
from aios.system_info import SystemInfoTool
from aios.system_memory import SystemMemoryTool
from aios.system_prompt import build_system_prompt
from aios.systemd_list import SystemdListTool
from aios.systemd_restart import SystemdRestartTool
from aios.systemd_status import SystemdStatusTool
from aios.tool_calls import ToolCallError, parse_tool_call
from aios.tools import ToolRegistry, ToolResult


MAX_TOOL_CALLS_PER_REQUEST = 5
DIAGNOSTIC_CALLS = (
    ("system.info", {}),
    ("system.memory", {}),
    ("system.disk", {"path": "/"}),
    ("process.list", {"limit": 20}),
    ("systemd.list", {"limit": 20}),
)
PermissionHandler = Callable[[PolicyDecision, str, dict[str, object]], bool]


def build_tool_registry(*, filesystem_roots: tuple[Path, ...] | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        SystemInfoTool(), SystemMemoryTool(), SystemDiskTool(), ProcessListTool(),
        SystemdStatusTool(), SystemdListTool(), SystemdRestartTool(),
        FilesystemListTool(filesystem_roots=filesystem_roots),
        FilesystemReadTool(filesystem_roots=filesystem_roots),
        FilesystemMkdirTool(filesystem_roots=filesystem_roots),
        FilesystemWriteTool(filesystem_roots=filesystem_roots),
        FilesystemUpdateTool(filesystem_roots=filesystem_roots),
    ):
        registry.register(tool)
    return registry


class Core:
    """One synchronous session; the caller owns the provider and history lifetime."""

    def __init__(
        self, provider: LLMProvider, history: TaskHistory, *,
        registry: ToolRegistry | None = None,
        permission_handler: PermissionHandler | None = None,
        filesystem_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self._provider = provider
        self._history = history
        roots = None if filesystem_roots is None else normalize_filesystem_roots(filesystem_roots)
        self._registry = registry
        if self._registry is None:
            self._registry = build_tool_registry() if roots is None else build_tool_registry(filesystem_roots=roots)
        self._policy = PolicyEngine(self._registry)
        self._permission_handler = permission_handler
        self._messages: list[Message] = [{"role": "system", "content": build_system_prompt(roots)}]

    def chat(self, text: str) -> str:
        """Process a message; return the reply or propagate the original error."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Message must be a non-empty string")
        return self._request(text.strip(), diagnostic=False)

    def diagnose(self) -> str:
        """Collect the five READ checks, then request one textual summary."""
        return self._request("/diagnose", diagnostic=True)

    def recent_history(self) -> list[dict[str, object]]:
        return self._history.recent()

    def _authorize(self, name: str, arguments: dict[str, object]) -> bool:
        decision = self._policy.evaluate(name)
        if decision is PolicyDecision.ALLOW:
            return True
        if self._permission_handler is None:
            return False
        # A frontend may present refusals, but it cannot override them.
        accepted = self._permission_handler(decision, name, arguments)
        return decision is PolicyDecision.CONFIRM and accepted is True

    def _tool_feedback(self, reply: str, task_id: int) -> Message | None:
        try:
            call = parse_tool_call(reply)
        except ToolCallError:
            if not reply.lstrip().startswith(("{", "[")):
                return None
            call_id = self._history.start_tool(task_id, None, None)
            result = ToolResult(success=False, error="Invalid tool call")
            return self._result_feedback(None, result, call_id)
        return self._execute_tool_feedback(
            call.tool, call.arguments,
            lambda arguments: self._authorize(call.tool, arguments), task_id,
        )

    def _execute_tool_feedback(
        self, name: str, arguments: dict[str, object],
        authorize: Callable[[dict[str, object]], bool], task_id: int,
    ) -> Message:
        history_arguments = arguments
        if name in {"filesystem.write", "filesystem.update"} and "content" in arguments:
            # Mask file contents before the initial insert, even for denied/invalid calls.
            history_arguments = {**arguments, "content": "[contenu du fichier non conservé]"}
        call_id = self._history.start_tool(task_id, name, history_arguments)
        try:
            result = self._registry.execute(name, arguments, authorize=authorize)
        except (KeyboardInterrupt, SystemExit):
            self._history.finish_tool(call_id, None)
            raise
        except Exception:
            self._history.finish_tool(call_id, ToolResult(success=False, error="Tool execution failed"))
            raise
        return self._result_feedback(name, result, call_id)

    def _result_feedback(self, name: str | None, result: ToolResult, call_id: int) -> Message:
        try:
            content = json.dumps(
                {"tool_result": {"tool": name, **asdict(result)}}, allow_nan=False,
            )
        except Exception:
            result = ToolResult(success=False, error="Invalid tool result")
            content = json.dumps({"tool_result": {"tool": name, **asdict(result)}})
        if name == "filesystem.read" and result.success:
            # Keep file contents in the model's context, never in SQLite/journals.
            result = ToolResult(success=True, data={
                **result.data, "content": "[contenu du fichier non conservé]",
            })
        self._history.finish_tool(call_id, result)
        return {"role": "user", "content": content}

    def _diagnostic_feedback(self, task_id: int) -> list[Message]:
        feedback = []
        for name, arguments in DIAGNOSTIC_CALLS:
            feedback.append(self._execute_tool_feedback(
                name, arguments,
                lambda _, name=name: self._policy.evaluate(name) is PolicyDecision.ALLOW,
                task_id,
            ))
        return feedback

    def _request(self, text: str, *, diagnostic: bool) -> str:
        task_id = self._history.start(text)
        pending: list[Message] = [*self._messages, {"role": "user", "content": text}]
        try:
            remaining_calls = MAX_TOOL_CALLS_PER_REQUEST
            if diagnostic:
                pending = [*pending, *self._diagnostic_feedback(task_id)]
                # Keep all observations if the summary fails; no automatic retry.
                self._messages = pending
                remaining_calls = 0
            reply = self._provider.chat(pending)
            for _ in range(remaining_calls):
                feedback = self._tool_feedback(reply, task_id)
                if feedback is None:
                    break
                pending = [*pending, {"role": "assistant", "content": reply}, feedback]
                # Preserve the outcome even if the follow-up response fails.
                self._messages = pending
                reply = self._provider.chat(pending)
            else:
                # Inspect only: no call may execute after the budget is consumed.
                if reply.lstrip().startswith(("{", "[")):
                    if diagnostic:
                        reply = (
                            "Diagnostic terminé sans synthèse : "
                            "aucun appel d'outil supplémentaire autorisé."
                        )
                    else:
                        reply = (
                            f"Limite de {MAX_TOOL_CALLS_PER_REQUEST} appels d'outils "
                            "atteinte pour cette requête."
                        )
        except (KeyboardInterrupt, SystemExit):
            self._history.finish(task_id, "interrupted")
            raise
        except Exception:
            self._history.finish(task_id, "failed")
            raise
        self._history.finish(task_id, "completed")
        self._messages = [*pending, {"role": "assistant", "content": reply}]
        return reply
