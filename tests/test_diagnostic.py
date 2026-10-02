"""Exercise the read-only diagnostic with real validators and simulated readings."""

import json
from unittest.mock import Mock

import pytest

from aios.__main__ import main
from aios.core import DIAGNOSTIC_CALLS, MAX_TOOL_CALLS_PER_REQUEST, build_tool_registry
from aios.config import Config
from aios.llm import FakeLLMProvider
from aios.ollama import OllamaError
from aios.policy import PolicyEngine
from aios.system_prompt import SYSTEM_PROMPT
from aios.tools import RiskLevel, ToolRegistry, ToolResult


CHECKS = {
    "system.info": {},
    "system.memory": {},
    "system.disk": {"path": "/"},
    "process.list": {"limit": 20},
    "systemd.list": {"limit": 20},
}
READINGS = {
    "system.info": {"hostname": "private-host", "os": "Linux", "kernel": "test", "architecture": "x86_64", "uptime_seconds": 120.0},
    "system.memory": {"total_bytes": 1000, "free_bytes": 100, "available_bytes": 250, "used_bytes": 750, "used_percent": 75.0},
    "system.disk": {"path": "/", "total_bytes": 2000, "free_bytes": 200, "used_bytes": 1800, "used_percent": 90.0},
    "process.list": {"processes": [{"pid": 1, "name": "private-process"}]},
    "systemd.list": {"services": [{"service": "private-demo.service", "load_state": "loaded", "active_state": "failed", "sub_state": "failed"}], "truncated": True},
}


@pytest.fixture
def diagnostic(tmp_path, monkeypatch):
    registry = build_tool_registry()
    executions = {}
    for tool in registry.list_tools():
        execution = Mock(return_value=ToolResult(success=True, data=READINGS.get(tool.name, {})))
        monkeypatch.setattr(tool, "_execute", execution)
        executions[tool.name] = execution
    monkeypatch.setattr("aios.core.build_tool_registry", lambda: registry)
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(data_dir=tmp_path))

    def run(provider, entries):
        reader = Mock(side_effect=entries)
        monkeypatch.setattr("builtins.input", reader)
        monkeypatch.setattr("aios.__main__.OllamaProvider", lambda _: provider)
        assert main([]) == 0
        assert reader.call_count == len(entries)
        for messages in provider.calls:
            assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
            assert sum(message["role"] == "system" for message in messages) == 1

    return registry, executions, run


def results(messages):
    return [json.loads(message["content"])["tool_result"] for message in messages[-5:]]


def test_diagnostic_validates_and_checks_policy_before_each_read_then_requests_one_summary(
    diagnostic, monkeypatch, capsys, tmp_path,
):
    registry, executions, run = diagnostic
    events = []
    evaluate = PolicyEngine.evaluate
    for name in CHECKS:
        tool = registry.get(name)
        validate = tool.validate_arguments

        def validation(arguments, name=name, validate=validate):
            events.append(("validate", name))
            validate(arguments)

        def execution(arguments, name=name):
            events.append(("execute", name))
            return ToolResult(success=True, data=READINGS[name])

        monkeypatch.setattr(tool, "validate_arguments", validation)
        executions[name].side_effect = execution

    def policy(engine, name):
        events.append(("policy", name))
        return evaluate(engine, name)

    monkeypatch.setattr(PolicyEngine, "evaluate", policy)
    confirmation = Mock(return_value=True)
    monkeypatch.setattr("aios.__main__.authorize_tool_call", confirmation)
    provider = FakeLLMProvider(["Bilan simulé fondé sur les lectures."])

    run(provider, [" /diagnose ", "/exit"])

    assert len(DIAGNOSTIC_CALLS) == MAX_TOOL_CALLS_PER_REQUEST == 5
    assert all(registry.get(name).risk_level is RiskLevel.READ for name in CHECKS)
    assert events == [(stage, name) for name in CHECKS for stage in ("validate", "policy", "execute")]
    assert len(provider.calls) == 1
    assert provider.calls[0][1] == {"role": "user", "content": "/diagnose"}
    assert len(provider.calls[0]) == 7
    assert results(provider.calls[0]) == [
        {"tool": name, "success": True, "data": READINGS[name], "error": None} for name in CHECKS
    ]
    for name, arguments in CHECKS.items():
        executions[name].assert_called_once_with(arguments)
    executions["systemd.status"].assert_not_called()
    executions["systemd.restart"].assert_not_called()
    confirmation.assert_not_called()
    assert capsys.readouterr() == ("Simple-AIOS\nBilan simulé fondé sur les lectures.\n", "")
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert len(logs.splitlines()) == 2
    assert "private" not in logs


@pytest.mark.parametrize("risk", [RiskLevel.CONFIRM, RiskLevel.DENY, None, "READ"])
def test_diagnostic_rechecks_risk_and_refuses_non_read_checks_without_confirmation(
    diagnostic, monkeypatch, risk,
):
    registry, executions, run = diagnostic

    def revoke_next_check(_arguments):
        registry.get("system.memory").risk_level = risk
        return ToolResult(success=True, data=READINGS["system.info"])

    executions["system.info"].side_effect = revoke_next_check
    confirmation = Mock(return_value=True)
    monkeypatch.setattr("aios.__main__.authorize_tool_call", confirmation)
    provider = FakeLLMProvider(["Mémoire non évaluée."])

    run(provider, ["/diagnose", "/exit"])

    readings = results(provider.calls[0])
    assert [item["success"] for item in readings] == [True, False, True, True, True]
    assert readings[1]["error"] == "Tool execution denied"
    executions["system.memory"].assert_not_called()
    confirmation.assert_not_called()


@pytest.mark.parametrize(("failure", "error"), [
    ("missing", "Unknown tool"),
    ("validation", "Invalid tool arguments"),
    ("policy", "Tool authorization failed"),
    ("execution", "Tool execution failed"),
    ("serialization", "Invalid tool result"),
])
def test_one_failed_check_does_not_block_remaining_readings_or_leak_details(
    diagnostic, monkeypatch, capsys, tmp_path, failure, error,
):
    registry, executions, run = diagnostic
    if failure == "missing":
        reduced = ToolRegistry()
        for tool in registry.list_tools():
            if tool.name != "system.memory":
                reduced.register(tool)
        monkeypatch.setattr("aios.core.build_tool_registry", lambda: reduced)
    elif failure == "validation":
        monkeypatch.setattr(registry.get("system.memory"), "validate_arguments", Mock(side_effect=ValueError("private detail")))
    elif failure == "policy":
        evaluate = PolicyEngine.evaluate

        def policy(engine, name):
            if name == "system.memory":
                raise RuntimeError("private detail")
            return evaluate(engine, name)

        monkeypatch.setattr(PolicyEngine, "evaluate", policy)
    elif failure == "execution":
        executions["system.memory"].side_effect = OSError("private detail")
    else:
        executions["system.memory"].return_value = ToolResult(success=True, data={"bad": object()})
    provider = FakeLLMProvider(["Bilan partiel."])

    run(provider, ["/diagnose", "/exit"])

    readings = results(provider.calls[0])
    assert readings[1] == {"tool": "system.memory", "success": False, "data": None, "error": error}
    assert [item["success"] for item in readings] == [True, False, True, True, True]
    assert executions["system.memory"].call_count == int(failure in {"execution", "serialization"})
    for name in CHECKS.keys() - {"system.memory"}:
        assert executions[name].call_count == 1
    captured = capsys.readouterr()
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "private detail" not in captured.out + captured.err + logs + repr(provider.calls)


def test_all_checks_can_fail_without_fabricating_measurements(diagnostic):
    _, executions, run = diagnostic
    for name in CHECKS:
        executions[name].side_effect = OSError("private detail")
    provider = FakeLLMProvider(["Diagnostic indisponible."])

    run(provider, ["/diagnose", "/exit"])

    assert all(not item["success"] and item["data"] is None for item in results(provider.calls[0]))
    assert all(executions[name].call_count == 1 for name in CHECKS)


@pytest.mark.parametrize("reply", [
    '{"tool":"systemd.restart","arguments":{"service":"demo.service"}}',
    '{"tool":"system.info","arguments":{}}',
    '{"tool":', '[]',
])
def test_model_cannot_run_any_additional_tool_during_the_diagnostic(
    diagnostic, monkeypatch, capsys, reply,
):
    _, executions, run = diagnostic
    dispatch = Mock(side_effect=AssertionError("No dispatch allowed during diagnostic summary"))
    monkeypatch.setattr("aios.core.Core._tool_feedback", dispatch)
    provider = FakeLLMProvider([reply, "Disponible"])

    run(provider, ["/diagnose", "/exit"])

    assert len(provider.calls) == 1
    dispatch.assert_not_called()
    assert all(executions[name].call_count == 1 for name in CHECKS)
    executions["systemd.restart"].assert_not_called()
    captured = capsys.readouterr()
    assert "aucun appel d'outil supplémentaire autorisé" in captured.out
    assert "Action à confirmer" not in captured.out


def test_provider_error_preserves_readings_without_repeating_them(diagnostic, capsys):
    _, executions, run = diagnostic

    class FailingOnceProvider(FakeLLMProvider):
        def chat(self, messages):
            reply = super().chat(messages)
            if len(self.calls) == 1:
                raise OllamaError("private provider detail")
            return reply

    provider = FailingOnceProvider(["unused", "Bilan repris."])

    run(provider, ["/diagnose", "Résume les résultats", "/exit"])

    assert provider.calls[1] == [*provider.calls[0], {"role": "user", "content": "Résume les résultats"}]
    assert len(results(provider.calls[0])) == 5
    assert all(executions[name].call_count == 1 for name in CHECKS)
    captured = capsys.readouterr()
    assert "Impossible d'obtenir une réponse du LLM." in captured.err
    assert captured.out == "Simple-AIOS\nBilan repris.\n"


def test_each_diagnostic_refreshes_all_readings(diagnostic):
    _, executions, run = diagnostic
    executions["system.info"].side_effect = [
        ToolResult(success=True, data={**READINGS["system.info"], "uptime_seconds": value})
        for value in (120.0, 130.0)
    ]
    provider = FakeLLMProvider(["Premier bilan", "Deuxième bilan"])

    run(provider, ["/diagnose", "/diagnose", "/exit"])

    assert [results(call)[0]["data"]["uptime_seconds"] for call in provider.calls] == [120.0, 130.0]
    assert all(executions[name].call_count == 2 for name in CHECKS)


def test_normal_conversation_gets_a_fresh_tool_budget_after_diagnostic(diagnostic):
    _, executions, run = diagnostic
    call = '{"tool":"system.info","arguments":{}}'
    provider = FakeLLMProvider(["Bilan", call, "Nouvelle observation"])

    run(provider, ["/diagnose", "Relis les informations", "/exit"])

    assert len(provider.calls) == 3
    assert executions["system.info"].call_count == 2
    assert all(executions[name].call_count == 1 for name in CHECKS.keys() - {"system.info"})


@pytest.mark.parametrize("command", ["/diagnose /tmp", "/diagnose --restart", "/diagnoses"])
def test_diagnostic_accepts_no_arguments_or_variant_commands(diagnostic, command, capsys):
    _, executions, run = diagnostic
    provider = FakeLLMProvider([])

    run(provider, [command, "/exit"])

    assert not provider.calls
    assert all(execution.call_count == 0 for execution in executions.values())
    assert "Commande inconnue" in capsys.readouterr().out
