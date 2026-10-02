"""Use the Core directly, without terminal operations, a real LLM or system actions."""

from contextlib import closing
import json
from unittest.mock import Mock

import pytest

from aios.core import Core, build_tool_registry
from aios.history import TaskHistory
from aios.llm import FakeLLMProvider
from aios.ollama import OllamaError
from aios.policy import PolicyDecision
from aios.system_prompt import SYSTEM_PROMPT
from aios.tools import RiskLevel, Tool, ToolRegistry, ToolResult


CALL = '{"tool":"test.echo","arguments":{}}'


@pytest.fixture(autouse=True)
def no_terminal(monkeypatch):
    blocked = Mock(side_effect=AssertionError("Core must not use the terminal"))
    monkeypatch.setattr("builtins.input", blocked)
    monkeypatch.setattr("builtins.print", blocked)
    monkeypatch.setattr("sys.stdin.isatty", blocked)
    yield
    blocked.assert_not_called()


class EchoTool(Tool):
    name = "test.echo"
    description = "Return a validated value for offline Core tests."
    risk_level = RiskLevel.READ

    def __init__(self):
        self.calls = []

    def validate_arguments(self, arguments):
        if arguments.keys() - {"target"}:
            raise ValueError("Invalid arguments")
        arguments.setdefault("target", "default")

    def _execute(self, arguments):
        self.calls.append(arguments.copy())
        return ToolResult(success=True, data=arguments)


@pytest.fixture
def components(tmp_path):
    registry = ToolRegistry()
    tool = EchoTool()
    registry.register(tool)
    with closing(TaskHistory(tmp_path)) as history:
        yield history, registry, tool


def test_core_sessions_have_separate_context_and_borrow_the_history(components, caplog):
    history, registry, _ = components
    first_provider = FakeLLMProvider(["Réponse A", "Suite A"])
    second_provider = FakeLLMProvider(["Réponse B"])
    first = Core(first_provider, history, registry=registry)
    second = Core(second_provider, history, registry=registry)

    assert first.chat("  Demande A  ") == "Réponse A"
    assert second.chat("Demande B") == "Réponse B"
    assert first.chat("Suite") == "Suite A"
    assert second_provider.calls == [[
        {"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "Demande B"},
    ]]
    assert first_provider.calls[1] == [
        *first_provider.calls[0], {"role": "assistant", "content": "Réponse A"},
        {"role": "user", "content": "Suite"},
    ]
    assert [task["task"] for task in first.recent_history()] == ["Suite", "Demande B", "Demande A"]
    assert all(task["status"] == "completed" for task in history.recent())
    assert not caplog.records


@pytest.mark.parametrize("text", [None, 42, "", " \t"])
def test_invalid_messages_never_start_a_task_or_call_the_provider(components, text):
    history, registry, _ = components
    provider = FakeLLMProvider([])
    core = Core(provider, history, registry=registry)
    with pytest.raises(ValueError):
        core.chat(text)
    assert core.recent_history() == [] and provider.calls == []


@pytest.mark.parametrize(("risk", "allowed"), [
    (RiskLevel.READ, True), (RiskLevel.CONFIRM, False), (RiskLevel.DENY, False),
])
def test_core_applies_policy_without_a_frontend_and_refuses_confirmation_by_default(components, risk, allowed):
    history, registry, tool = components
    tool.risk_level = risk
    provider = FakeLLMProvider([CALL, "Résultat"])
    core = Core(provider, history, registry=registry)
    assert core.chat("Demande") == "Résultat"
    assert len(tool.calls) == int(allowed)
    result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
    assert result["success"] is allowed
    if not allowed:
        assert result["error"] == "Tool execution denied"


@pytest.mark.parametrize(("risk", "answer", "allowed", "presented"), [
    (RiskLevel.READ, True, True, False),
    (RiskLevel.DENY, True, False, True),
    (RiskLevel.CONFIRM, True, True, True),
    (RiskLevel.CONFIRM, False, False, True),
    (RiskLevel.CONFIRM, "oui", False, True),
    (RiskLevel.CONFIRM, 1, False, True),
    (RiskLevel.CONFIRM, None, False, True),
])
def test_frontend_cannot_override_deny_or_modify_validated_execution_arguments(
    components, risk, answer, allowed, presented,
):
    history, registry, tool = components
    tool.risk_level = risk
    decisions = []

    def permissions(decision, name, arguments):
        decisions.append((decision, name, arguments.copy()))
        arguments["target"] = "frontend mutation"
        return answer

    core = Core(FakeLLMProvider([CALL, "Résultat"]), history, registry=registry, permission_handler=permissions)
    assert core.chat("Demande") == "Résultat"
    assert tool.calls == ([{"target": "default"}] if allowed else [])
    if presented:
        expected = PolicyDecision.DENY if risk is RiskLevel.DENY else PolicyDecision.CONFIRM
        assert decisions == [(expected, tool.name, {"target": "default"})]
    else:
        assert decisions == []


def test_permission_handler_error_fails_closed_without_leaking_details(components, caplog):
    history, registry, tool = components
    tool.risk_level = RiskLevel.CONFIRM
    handler = Mock(side_effect=RuntimeError("private confirmation error"))
    provider = FakeLLMProvider([CALL, "Refus reçu"])
    core = Core(provider, history, registry=registry, permission_handler=handler)
    assert core.chat("Demande") == "Refus reçu"
    assert tool.calls == []
    result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
    assert result["error"] == "Tool authorization failed"
    assert "private confirmation error" not in repr(core.recent_history()) + repr(provider.calls)
    assert not caplog.records


def test_core_keeps_the_five_attempt_budget_without_a_terminal(components):
    history, registry, tool = components
    provider = FakeLLMProvider([CALL] * 6 + ["Nouvelle réponse"])
    core = Core(provider, history, registry=registry)
    assert core.chat("Première demande") == "Limite de 5 appels d'outils atteinte pour cette requête."
    assert len(tool.calls) == 5 and len(provider.calls) == 6
    assert len(core.recent_history()[0]["tools"]) == 5
    assert core.chat("Nouvelle demande") == "Nouvelle réponse"
    assert len(core.recent_history()) == 2


def test_diagnostic_is_read_only_even_with_a_permissive_frontend(components, monkeypatch):
    history, _, _ = components
    registry = build_tool_registry()
    executions = {}
    for tool in registry.list_tools():
        execution = Mock(return_value=ToolResult(success=True, data={"observed": tool.name}))
        executions[tool.name] = execution
        monkeypatch.setattr(tool, "_execute", execution)
    registry.get("system.memory").risk_level = RiskLevel.CONFIRM
    handler = Mock(return_value=True)
    reply = '{"tool":"systemd.restart","arguments":{"service":"demo.service"}}'
    provider = FakeLLMProvider([reply])
    core = Core(provider, history, registry=registry, permission_handler=handler)

    assert "aucun appel d'outil supplémentaire autorisé" in core.diagnose()
    assert len(provider.calls) == 1
    assert provider.calls[0][1] == {"role": "user", "content": "/diagnose"}
    assert [call["status"] for call in core.recent_history()[0]["tools"]] == [
        "succeeded", "failed", "succeeded", "succeeded", "succeeded",
    ]
    handler.assert_not_called()
    executions["system.memory"].assert_not_called()
    executions["systemd.restart"].assert_not_called()
    executions["systemd.status"].assert_not_called()


def test_provider_failure_is_propagated_with_tool_outcome_preserved(components, caplog):
    history, registry, tool = components
    provider = FakeLLMProvider([CALL, "unused", "Reprise"])
    chat = provider.chat
    error = OllamaError("private provider failure")

    def respond(messages):
        reply = chat(messages)
        if len(provider.calls) == 2:
            raise error
        return reply

    provider.chat = respond
    core = Core(provider, history, registry=registry)
    with pytest.raises(OllamaError) as raised:
        core.chat("Demande")
    assert raised.value is error
    task = core.recent_history()[0]
    assert task["status"] == "failed" and task["tools"][0]["status"] == "succeeded"
    assert core.chat("Suite") == "Reprise"
    assert provider.calls[2] == [*provider.calls[1], {"role": "user", "content": "Suite"}]
    assert len(tool.calls) == 1
    assert "private provider failure" not in repr(core.recent_history())
    assert not caplog.records


@pytest.mark.parametrize(("error", "status"), [
    (KeyboardInterrupt(), "interrupted"), (RuntimeError("private failure"), "failed"),
])
def test_core_preserves_status_and_propagates_interruptions_and_unexpected_errors(components, error, status):
    history, registry, _ = components
    provider = FakeLLMProvider([])
    provider.chat = Mock(side_effect=error)
    core = Core(provider, history, registry=registry)
    with pytest.raises(type(error)):
        core.chat("Demande")
    task = core.recent_history()[0]
    assert task["status"] == status and task["tools"] == []
    assert provider.chat.call_count == 1
