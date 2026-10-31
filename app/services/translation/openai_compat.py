"""Provider for OpenAI-compatible endpoints (Groq, OpenRouter, Ollama)."""

from __future__ import annotations

import httpx

from app.errors import (
    MalformedTranslationResponse,
    ProviderConfigurationError,
    RateLimitError,
    TransientTranslationError,
    TranslationError,
)
from app.services.translation.base import TranslationProvider
from app.services.translation.parsing import parse_translation_payload
from app.services.translation.prompts import build_batch_prompt


class OpenAICompatibleTranslationProvider(TranslationProvider):
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not base_url:
            raise ProviderConfigurationError(
                "OPENAI_COMPAT_BASE_URL is not set for the openai_compatible provider."
            )
        if not model:
            raise ProviderConfigurationError(
                "OPENAI_COMPAT_MODEL is not set for the openai_compatible provider."
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout_seconds

    def translate(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        prompt = build_batch_prompt(texts, source_language, target_language)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a translation engine. Reply with JSON only. "
                        "Never add commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise TransientTranslationError(
                "The translation provider timed out. Please try again."
            ) from exc
        except httpx.HTTPError as exc:
            raise TransientTranslationError(
                "The translation provider could not be reached."
            ) from exc

        if response.status_code == 429:
            raise RateLimitError()
        if response.status_code in (401, 403):
            raise ProviderConfigurationError(
                "The translation provider rejected the API key."
            )
        if response.status_code >= 500:
            raise TransientTranslationError()
        if response.status_code >= 400:
            raise TranslationError(
                "The translation provider rejected the request "
                f"(HTTP {response.status_code})."
            )

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise MalformedTranslationResponse() from exc

        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if not isinstance(content, str):
            raise MalformedTranslationResponse()

        return parse_translation_payload(content, len(texts))
