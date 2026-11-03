"""OpenAI provider using the official openai Python SDK."""

from __future__ import annotations

from app.errors import (
    MalformedTranslationResponse,
    ProviderConfigurationError,
    RateLimitError,
    TransientTranslationError,
    TranslationError,
)
from app.services.translation.base import TranslationProvider
from app.services.translation.parsing import parse_translation_payload
from app.services.translation.prompts import (
    TRANSLATION_SYSTEM_PROMPT,
    build_batch_prompt,
)


class OpenAITranslationProvider(TranslationProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ProviderConfigurationError(
                "OpenAI is selected but OPENAI_API_KEY is not set. "
                "Add it to .env or set AI_PROVIDER=mock."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderConfigurationError(
                "The OpenAI SDK is not installed. Install requirements.txt."
            ) from exc

        self.model = model or "gpt-4o-mini"

        try:
            self._client = OpenAI(
                api_key=api_key,
                timeout=timeout_seconds,
                max_retries=0,
            )
        except Exception as exc:
            raise ProviderConfigurationError(
                "The OpenAI client could not be initialised. "
                "Check OPENAI_API_KEY and the installed openai package."
            ) from exc

    def translate(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        if not texts:
            return []

        prompt = build_batch_prompt(texts, source_language, target_language)

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as exc:
            raise _classify_openai_error(exc) from exc

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise MalformedTranslationResponse() from exc

        if not isinstance(content, str) or not content.strip():
            raise MalformedTranslationResponse(
                "OpenAI returned an empty response."
            )

        return parse_translation_payload(content, len(texts))


def _classify_openai_error(exc: Exception) -> TranslationError:
    name = type(exc).__name__
    status_code = getattr(exc, "status_code", None)
    message = str(exc).lower()

    if (
        isinstance(exc, TimeoutError)
        or "timeout" in name.lower()
        or "timed out" in message
        or "timeout" in message
    ):
        return TransientTranslationError(
            "The OpenAI request timed out. Please try again."
        )
    if (
        status_code == 429
        or name == "RateLimitError"
        or "rate limit" in message
        or "quota" in message
    ):
        return RateLimitError()
    if (
        status_code in (401, 403)
        or name in {"AuthenticationError", "PermissionDeniedError"}
        or "api key" in message
        or "authentication" in message
        or "unauthorized" in message
    ):
        return ProviderConfigurationError(
            "OpenAI rejected the API key. Check OPENAI_API_KEY on the server."
        )
    if (
        status_code == 404
        or name == "NotFoundError"
        or ("model" in message and "not found" in message)
    ):
        return ProviderConfigurationError(
            "The configured OpenAI model is not available. Check OPENAI_MODEL."
        )
    if (
        (isinstance(status_code, int) and 500 <= status_code < 600)
        or name in {"InternalServerError", "APIConnectionError"}
        or "connection" in name.lower()
        or "temporarily unavailable" in message
        or "overloaded" in message
    ):
        return TransientTranslationError()
    return TranslationError("OpenAI could not complete the translation request.")
