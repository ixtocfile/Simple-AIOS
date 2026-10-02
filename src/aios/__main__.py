"""Entry point for ``python -m aios``."""

import argparse
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from importlib.metadata import version
import json
import logging
import sys

from aios.app_logging import close_logging, configure_logging
from aios.config import load_config
from aios.history import HISTORY_LIMIT, TaskHistory
from aios.llm import LLMProvider, Message
from aios.ollama import OllamaError, OllamaProvider
from aios.policy import PolicyDecision, PolicyEngine
from aios.process_list import ProcessListTool
from aios.system_disk import SystemDiskTool
from aios.system_info import SystemInfoTool
from aios.system_memory import SystemMemoryTool
from aios.system_prompt import SYSTEM_PROMPT
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


def authorize_tool_call(
    policy: PolicyEngine, tool_name: str, arguments: dict[str, object],
) -> bool:
    """Apply a policy decision in the terminal, without executing the tool."""
    decision = policy.evaluate(tool_name)
    if decision is PolicyDecision.ALLOW:
        return True
    if decision is not PolicyDecision.CONFIRM:
        print("Action refusée.")
        return False

    accepted = False
    try:
        if not sys.stdin.isatty():
            print("Confirmation indisponible : terminal interactif requis.")
        else:
            if not isinstance(arguments, dict) or any(
                not isinstance(key, str) for key in arguments
            ):
                raise ValueError("Arguments must be a string-keyed dictionary")
            # Escape control characters so arguments cannot rewrite the prompt.
            preview = json.dumps(
                {"outil": tool_name, "arguments": arguments},
                ensure_ascii=True, allow_nan=False,
            )
            print(f"Action à confirmer : {preview}")
            answer = input("Confirmer cette action ? Tapez oui [oui/NON] : ")
            accepted = answer.strip().casefold() == "oui"
    except (EOFError, KeyboardInterrupt):
        print()
    except (OSError, TypeError, ValueError):
        # An unreadable confirmation or an unrepresentable action is refused.
        pass
    if not accepted:
        print("Action refusée.")
    return accepted


def _build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        SystemInfoTool(), SystemMemoryTool(), SystemDiskTool(), ProcessListTool(),
        SystemdStatusTool(), SystemdListTool(), SystemdRestartTool(),
    ):
        registry.register(tool)
    return registry


def _tool_feedback(
    reply: str, registry: ToolRegistry, policy: PolicyEngine,
    history: TaskHistory, task_id: int,
) -> Message | None:
    try:
        call = parse_tool_call(reply)
    except ToolCallError:
        if not reply.lstrip().startswith(("{", "[")):
            return None
        call_id = history.start_tool(task_id, None, None)
        result = ToolResult(success=False, error="Invalid tool call")
        return _result_feedback(None, result, history, call_id)
    else:
        return _execute_tool_feedback(
            call.tool, call.arguments, registry,
            lambda arguments: authorize_tool_call(policy, call.tool, arguments),
            history, task_id,
        )


def _execute_tool_feedback(
    name: str, arguments: dict[str, object], registry: ToolRegistry,
    authorize: Callable[[dict[str, object]], bool], history: TaskHistory, task_id: int,
) -> Message:
    call_id = history.start_tool(task_id, name, arguments)
    try:
        result = registry.execute(name, arguments, authorize=authorize)
    except (KeyboardInterrupt, SystemExit):
        history.finish_tool(call_id, None)
        raise
    except Exception:
        history.finish_tool(call_id, ToolResult(success=False, error="Tool execution failed"))
        raise
    return _result_feedback(name, result, history, call_id)


def _result_feedback(
    name: str | None, result: ToolResult, history: TaskHistory, call_id: int,
) -> Message:
    try:
        content = json.dumps(
            {"tool_result": {"tool": name, **asdict(result)}}, allow_nan=False,
        )
    except Exception:
        result = ToolResult(success=False, error="Invalid tool result")
        content = json.dumps({"tool_result": {"tool": name, **asdict(result)}})
    history.finish_tool(call_id, result)
    # Keep the existing text-chat contract; this is application-generated data.
    return {"role": "user", "content": content}


def _diagnostic_feedback(
    registry: ToolRegistry, policy: PolicyEngine, history: TaskHistory, task_id: int,
) -> list[Message]:
    """Collect the fixed READ checks; CONFIRM and DENY never prompt or execute."""
    feedback = []
    for name, arguments in DIAGNOSTIC_CALLS:
        feedback.append(_execute_tool_feedback(
            name, arguments, registry,
            lambda _, name=name: policy.evaluate(name) is PolicyDecision.ALLOW,
            history, task_id,
        ))
    return feedback


def _show_history(history: TaskHistory) -> None:
    tasks = history.recent()
    if not tasks:
        print("Historique vide.")
        return
    print(f"Historique ({HISTORY_LIMIT} dernières tâches, plus récentes d'abord) :")
    for task in tasks:
        # Escape all stored text, including terminal controls and Unicode bidi.
        summary = {key: value for key, value in task.items() if key != "tools"}
        print("Tâche : " + json.dumps(summary, ensure_ascii=True, allow_nan=False))
        for call in task["tools"]:
            print("  Outil : " + json.dumps(call, ensure_ascii=True, allow_nan=False))


def _run_shell(provider: LLMProvider, history: TaskHistory) -> None:
    print("Simple-AIOS")
    messages: list[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
    logger = logging.getLogger("aios")
    registry = _build_tool_registry()
    policy = PolicyEngine(registry)

    while True:
        try:
            command = input("ai> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not command:
            continue
        if command == "/exit":
            return
        if command == "/help":
            print(
                "Écrivez un message pour discuter avec le LLM.\n"
                "/help - Afficher l'aide\n"
                "/version - Afficher la version\n"
                "/diagnose - Diagnostic général en lecture seule\n"
                "/history - Afficher les dernières tâches et leurs outils\n"
                "/exit - Quitter"
            )
        elif command == "/version":
            print(f"Simple-AIOS {version('simple-aios')}")
        elif command == "/history":
            _show_history(history)
        elif command.startswith("/") and command != "/diagnose":
            print("Commande inconnue. Tapez /help pour afficher l'aide.")
        else:
            task_id = history.start(command)
            pending: list[Message] = [*messages, {"role": "user", "content": command}]
            try:
                remaining_calls = MAX_TOOL_CALLS_PER_REQUEST
                if command == "/diagnose":
                    pending = [*pending, *_diagnostic_feedback(registry, policy, history, task_id)]
                    # Keep all observations if the summary fails; no automatic retry.
                    messages = pending
                    # The five checks have already consumed the budget: summary only.
                    remaining_calls = 0
                reply = provider.chat(pending)
                for _ in range(remaining_calls):
                    feedback = _tool_feedback(reply, registry, policy, history, task_id)
                    if feedback is None:
                        break
                    pending = [*pending, {"role": "assistant", "content": reply}, feedback]
                    # Preserve the outcome even if the follow-up response fails.
                    messages = pending
                    reply = provider.chat(pending)
                else:
                    # Inspect only: no call may execute after the budget is consumed.
                    if reply.lstrip().startswith(("{", "[")):
                        if command == "/diagnose":
                            reply = (
                                "Diagnostic terminé sans synthèse : "
                                "aucun appel d'outil supplémentaire autorisé."
                            )
                        else:
                            reply = (
                                f"Limite de {MAX_TOOL_CALLS_PER_REQUEST} appels d'outils "
                                "atteinte pour cette requête."
                            )
            except OllamaError as error:
                history.finish(task_id, "failed")
                logger.error("Provider error (%s)", type(error).__name__)
                print(
                    "Impossible d'obtenir une réponse du LLM. "
                    "Vérifiez Ollama et le modèle configuré.",
                    file=sys.stderr,
                )
                continue
            except (KeyboardInterrupt, SystemExit):
                history.finish(task_id, "interrupted")
                raise
            except Exception:
                history.finish(task_id, "failed")
                raise
            history.finish(task_id, "completed")
            messages = [*pending, {"role": "assistant", "content": reply}]
            print(reply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simple-AIOS")
    parser.add_argument("--config", metavar="FILE", help="Fichier de configuration TOML")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        logger = configure_logging(config)
    except (OSError, ValueError):
        print("Impossible de charger la configuration ou d'initialiser les logs.", file=sys.stderr)
        return 1

    logger.info("Application started")
    try:
        if config.provider != "ollama":
            logger.error("Unsupported LLM provider")
            print('Provider LLM non pris en charge. Utilisez provider = "ollama".', file=sys.stderr)
            return 1
        with closing(TaskHistory(config.data_dir)) as history:
            _run_shell(OllamaProvider(config), history)
    except KeyboardInterrupt:
        print()
    except Exception as error:
        # Exception messages and tracebacks can contain user data or credentials.
        logger.error("Application error (%s)", type(error).__name__)
        print("Une erreur est survenue. Consultez les logs.", file=sys.stderr)
        return 1
    finally:
        logger.info("Application stopped")
        close_logging()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
