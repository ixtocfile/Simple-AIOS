"""Check strict JSON envelopes without tool execution or a real LLM."""

from dataclasses import asdict
import json
from unittest.mock import Mock

import pytest

from aios.llm import FakeLLMProvider
from aios.tool_calls import (
    MAX_TOOL_CALL_DEPTH, MAX_TOOL_CALL_LENGTH, ToolCall, ToolCallError, parse_tool_call,
)


@pytest.mark.parametrize(("name", "arguments"), [
    ("system.info", {}), ("system.memory", {}),
    ("system.disk", {"path": "/mnt/données"}), ("process.list", {"limit": 10}),
])
def test_existing_tool_call_envelopes(name, arguments):
    raw = json.dumps({"tool": name, "arguments": arguments}, ensure_ascii=False)

    call = parse_tool_call(raw)

    assert call == ToolCall(tool=name, arguments=arguments)
    assert asdict(call) == json.loads(raw)


def test_key_order_whitespace_and_nested_json_values_are_preserved():
    arguments = {
        "text": "NaN is text, not a number\n", "nothing": None,
        "items": [True, False, 0, -3, 1.25, {"unicode": "é🌍"}],
    }
    raw = " \n" + json.dumps({"arguments": arguments, "tool": "test.values"}) + "\t\r\n"

    call = parse_tool_call(raw)

    assert call.tool == "test.values"
    assert call.arguments == arguments
    assert type(call.arguments["items"][0]) is bool
    assert type(call.arguments["items"][2]) is int
    assert type(call.arguments["items"][4]) is float


@pytest.mark.parametrize("raw", [None, {}, [], b'{"tool":"system.info","arguments":{}}'])
def test_only_text_input_is_accepted(raw):
    with pytest.raises(ToolCallError, match="^Invalid tool call$"):
        parse_tool_call(raw)


@pytest.mark.parametrize("raw", [
    "", " \n", "null", "true", "42", '"system.info"',
    '[{"tool":"system.info","arguments":{}}]',
    '{"tool":"system.info","arguments":{},}',
    "{'tool':'system.info','arguments':{}}",
    '```json\n{"tool":"system.info","arguments":{}}\n```',
    'Voici : {"tool":"system.info","arguments":{}}',
    '{"tool":"system.info","arguments":{}} terminé',
    '{"tool":"system.info","arguments":{}}{"tool":"system.memory","arguments":{}}',
    '{"tool":"system.info","arguments":{"text":"raw\nnewline"}}',
])
def test_malformed_or_non_single_object_json_is_rejected(raw):
    with pytest.raises(ToolCallError, match="^Invalid tool call$"):
        parse_tool_call(raw)


@pytest.mark.parametrize("payload", [
    {}, {"tool": "system.info"}, {"arguments": {}},
    {"tool": "system.info", "arguments": {}, "risk_level": "READ"},
    {"tool": "system.info", "arguments": {}, "confirmed": True},
    {"tool": "system.info", "arguments": {}, "extra": None},
])
def test_missing_or_extra_fields_are_rejected(payload):
    with pytest.raises(ToolCallError):
        parse_tool_call(json.dumps(payload))


@pytest.mark.parametrize("name", [
    None, True, 42, [], "", " ", " system.info", "system.info ",
    "system.\tinfo", "system.\x1binfo", "system.\u202einfo",
])
def test_invalid_names_are_rejected_without_normalization(name):
    with pytest.raises(ToolCallError):
        parse_tool_call(json.dumps({"tool": name, "arguments": {}}))


@pytest.mark.parametrize("arguments", [None, True, 42, "{}", []])
def test_arguments_must_be_an_object(arguments):
    with pytest.raises(ToolCallError):
        parse_tool_call(json.dumps({"tool": "system.info", "arguments": arguments}))


@pytest.mark.parametrize("raw", [
    '{"tool":"system.info","tool":"system.disk","arguments":{}}',
    '{"tool":"system.info","arguments":{},"arguments":{"extra":1}}',
    '{"tool":"system.info","arguments":{},"to\\u006fl":"system.disk"}',
    '{"tool":"system.disk","arguments":{"path":"/","path":"/tmp"}}',
    '{"tool":"test.values","arguments":{"items":[{"x":1,"x":2}]}}',
])
def test_duplicate_keys_are_rejected_at_every_depth(raw):
    with pytest.raises(ToolCallError):
        parse_tool_call(raw)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"])
def test_non_finite_numbers_are_rejected_in_nested_arguments(number):
    raw = '{"tool":"test.values","arguments":{"items":[{"value":' + number + '}]}}'
    with pytest.raises(ToolCallError):
        parse_tool_call(raw)


def test_length_limit_is_checked_before_decoding(monkeypatch):
    decoder = Mock(side_effect=AssertionError("Oversized input must not be decoded"))
    monkeypatch.setattr("aios.tool_calls.json.loads", decoder)

    with pytest.raises(ToolCallError):
        parse_tool_call(" " * (MAX_TOOL_CALL_LENGTH + 1))

    decoder.assert_not_called()


def test_document_at_the_length_limit_is_accepted():
    prefix = '{"tool":"test.values","arguments":{"text":"'
    suffix = '"}}'
    value = "a" * (MAX_TOOL_CALL_LENGTH - len(prefix) - len(suffix))

    call = parse_tool_call(prefix + value + suffix)

    assert call.arguments == {"text": value}


@pytest.mark.parametrize("too_deep", [False, True])
@pytest.mark.parametrize("container", ["object", "array"])
def test_container_depth_limit(too_deep, container):
    # The envelope and arguments object already occupy two levels.
    nested = "value"
    for _ in range(MAX_TOOL_CALL_DEPTH - 2 + int(too_deep)):
        nested = {"child": nested} if container == "object" else [nested]
    raw = json.dumps({"tool": "test.values", "arguments": {"items": nested}})

    if too_deep:
        with pytest.raises(ToolCallError, match="^Invalid tool call$"):
            parse_tool_call(raw)
    else:
        assert parse_tool_call(raw).arguments == {"items": nested}


def test_failure_does_not_expose_or_log_raw_content(caplog, capsys):
    raw = '{"tool":"system.info","arguments":{"password":"secret-value"},"private-field":1}'

    with pytest.raises(ToolCallError) as caught:
        parse_tool_call(raw)

    assert str(caught.value) == "Invalid tool call"
    assert caught.value.__suppress_context__
    assert caught.value.__cause__ is None
    assert not hasattr(caught.value, "doc")
    assert not caplog.records
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_fake_response_is_parsed_without_registry_policy_or_execution(monkeypatch, caplog):
    blocked = Mock(side_effect=AssertionError("Parsing must not dispatch an action"))
    for target in (
        "aios.tools.ToolRegistry.get", "aios.tools.ToolRegistry.execute",
        "aios.tools.Tool.execute", "aios.policy.PolicyEngine.evaluate", "builtins.input",
    ):
        monkeypatch.setattr(target, blocked)
    raw = '{"tool":"test.unknown","arguments":{"confirmed":true,"value":"unchanged"}}'
    provider = FakeLLMProvider([raw])
    messages = [{"role": "user", "content": "Propose un appel"}]

    call = parse_tool_call(provider.chat(messages))

    assert call == ToolCall(
        tool="test.unknown", arguments={"confirmed": True, "value": "unchanged"},
    )
    assert provider.calls == [messages]
    blocked.assert_not_called()
    assert not caplog.records


def test_separate_parses_have_independent_arguments():
    raw = '{"tool":"test.values","arguments":{"items":[1]}}'
    first = parse_tool_call(raw)
    second = parse_tool_call(raw)

    first.arguments["items"].append(2)

    assert second.arguments == {"items": [1]}
