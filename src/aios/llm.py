"""Minimal text-chat contract and deterministic provider for offline tests."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Literal, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: Sequence[Message]) -> str:
        """Return assistant text without modifying the supplied messages."""
        raise NotImplementedError


class FakeLLMProvider(LLMProvider):
    """Consume scripted replies and keep independent copies of calls in memory."""

    def __init__(self, responses: Sequence[str]) -> None:
        if isinstance(responses, str):
            raise TypeError("responses must be a sequence of strings, not a string")
        replies = tuple(responses)
        if any(not isinstance(reply, str) for reply in replies):
            raise TypeError("Each fake response must be a string")
        self._responses = iter(replies)
        self.calls: list[list[Message]] = []

    def chat(self, messages: Sequence[Message]) -> str:
        self.calls.append([message.copy() for message in messages])
        try:
            return next(self._responses)
        except StopIteration:
            raise RuntimeError("No fake response remaining") from None
