"""Exercise the provider contract without an LLM, network or credentials."""

import pytest

from aios.llm import FakeLLMProvider, LLMProvider, Message


def test_provider_requires_a_chat_implementation():
    with pytest.raises(TypeError):
        LLMProvider()


def test_scripted_conversation_through_provider_interface():
    fake = FakeLLMProvider(["Bonjour !", "Très bien."])
    provider: LLMProvider = fake
    messages: list[Message] = [
        {"role": "system", "content": "Réponds en français."},
        {"role": "user", "content": "Bonjour"},
    ]

    first_reply = provider.chat(messages)
    assert first_reply == "Bonjour !"
    messages.extend([
        {"role": "assistant", "content": first_reply},
        {"role": "user", "content": "Comment vas-tu ?"},
    ])
    assert provider.chat(messages) == "Très bien."
    assert len(fake.calls[0]) == 2
    assert fake.calls[1] == messages


@pytest.mark.parametrize("responses", [[], ["only reply"]])
def test_exhaustion_fails_explicitly_and_records_the_attempt(responses):
    provider = FakeLLMProvider(responses)
    for response in responses:
        assert provider.chat([]) == response

    with pytest.raises(RuntimeError, match="No fake response remaining"):
        provider.chat([])

    assert len(provider.calls) == len(responses) + 1


def test_messages_and_recorded_calls_are_independent():
    provider = FakeLLMProvider(["reply"])
    messages: list[Message] = [{"role": "user", "content": "original"}]

    provider.chat(messages)

    assert messages == [{"role": "user", "content": "original"}]
    messages[0]["content"] = "changed"
    messages.clear()
    assert provider.calls == [[{"role": "user", "content": "original"}]]


def test_script_is_copied_at_construction():
    responses = ["original"]
    provider = FakeLLMProvider(responses)
    responses[0] = "changed"

    assert provider.chat([]) == "original"


def test_instances_have_independent_replies_and_calls():
    first = FakeLLMProvider(["first"])
    second = FakeLLMProvider(["second"])

    assert first.chat([]) == "first"
    assert second.calls == []
    assert second.chat([]) == "second"


@pytest.mark.parametrize("responses", ["single string", [42]])
def test_invalid_response_scripts_are_rejected(responses):
    with pytest.raises(TypeError):
        FakeLLMProvider(responses)
