"""Minimal Ollama chat provider using only the Python standard library."""

from collections.abc import Sequence
from http.client import HTTPException
import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aios.config import Config
from aios.llm import LLMProvider, Message


class OllamaError(RuntimeError):
    """Ollama could not provide a valid chat response."""


class OllamaProvider(LLMProvider):
    """Non-streaming chat with a timeout for each blocking socket operation."""

    def __init__(self, config: Config, *, timeout: float = 60.0) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        self._url = config.ollama_url.rstrip("/") + "/api/chat"
        self._model = config.model
        self._timeout = timeout

    def chat(self, messages: Sequence[Message]) -> str:
        body = json.dumps({
            "model": self._model,
            "messages": list(messages),
            "stream": False,
        }).encode("utf-8")
        request = Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            error.close()
            raise OllamaError(f"Ollama returned HTTP {error.code}") from None
        except TimeoutError:
            raise OllamaError("Ollama request timed out") from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise OllamaError("Ollama request timed out") from None
            raise OllamaError("Could not reach Ollama") from None
        except (OSError, HTTPException):
            raise OllamaError("Ollama connection failed") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OllamaError("Invalid Ollama response") from None

        if not isinstance(result, dict):
            raise OllamaError("Invalid Ollama response")
        if "error" in result:
            raise OllamaError("Ollama reported an error")
        message = result.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise OllamaError("Invalid Ollama response")
        return message["content"]
