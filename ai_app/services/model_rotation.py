"""
Backward-compatible adapter over `ai_app.engine.providers`.

Preserves the `OpenAIService` class signature used by legacy views/services while
routing all execution through the new provider abstraction:
- Fixes the hardcoded `model="llama2"` streaming bug in Ollama
- Removes raw `print(content, end="", flush=True)` stdout pollution
- Supports `FakeModelProvider` when `DEFAULT_MODEL_PROVIDER=fake` or when no API key is set
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator

from ai_app.engine.providers import ModelProvider, ProviderResponse, get_model_provider

logger = logging.getLogger("ai_app")


class OpenAIService:
    """Adapter bridging legacy `OpenAIService` calls to `ModelProvider`."""

    def __init__(
        self,
        use_ollama: bool = False,
        model_name: str | None = None,
        provider_name: str | None = None,
    ) -> None:
        self.use_ollama = use_ollama
        default_provider = provider_name or os.getenv("DEFAULT_MODEL_PROVIDER", "fake")
        if use_ollama:
            self.model_name = model_name or os.getenv("DEFAULT_OLLAMA_MODEL", "llama3.2")
            self.provider: ModelProvider = get_model_provider(
                "ollama", use_ollama=True, model_name=self.model_name
            )
        else:
            # Fall back to deterministic fake provider if github_models is selected without token
            if default_provider in {"github_models", "openai"} and not (
                os.getenv("GITHUB_TOKEN") or os.getenv("OPENAI_API_KEY")
            ):
                logger.info(
                    "No GITHUB_TOKEN/OPENAI_API_KEY found in environment; using FakeModelProvider."
                )
                default_provider = "fake"
            self.model_name = model_name or os.getenv("DEFAULT_HOSTED_MODEL", "gpt-4o-mini")
            self.provider = get_model_provider(
                default_provider, use_ollama=False, model_name=self.model_name
            )

    def create_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        top_p: float = 1.0,
        response_format: str | None = None,
    ) -> str:
        resp: ProviderResponse = self.provider.complete(
            messages=messages,
            model=self.model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return resp.content

    def create_streaming_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> Iterator[str]:
        yield from self.provider.stream(
            messages=messages,
            model=self.model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
