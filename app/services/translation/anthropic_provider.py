"""Anthropic Claude provider using the official anthropic Python SDK."""

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

# Application-selected conservative output cap. This is NOT the model maximum
# (Claude Sonnet 4.5 supports up to 64,000 output tokens); it is a safe
# default to avoid oversized batches. Reduce AI_BATCH_SIZE if a batch exceeds
# this, or raise the constant after verifying model documentation.
ANTHROPIC_MAX_OUTPUT_TOKENS = 8192


class AnthropicTranslationProvider(TranslationProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ProviderConfigurationError(
                "Anthropic is selected but ANTHROPIC_API_KEY is not set. "
                "Add it to .env or set AI_PROVIDER=mock."
            )

        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderConfigurationError(
                "The Anthropic SDK is not installed. Install requirements.txt."
            ) from exc

        self.model = model or "claude-sonnet-4-5"
        self.max_tokens = ANTHROPIC_MAX_OUTPUT_TOKENS

        try:
            self._client = Anthropic(
                api_key=api_key,
                timeout=timeout_seconds,
                max_retries=0,
            )
        except Exception as exc:
            raise ProviderConfigurationError(
                "The Anthropic client could not be initialised. "
                "Check ANTHROPIC_API_KEY and the installed anthropic package."
            ) from exc

    def translate(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        if not texts:
            return []

        prompt = build_batch_prompt(texts, source_language, target_language)

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.2,
                system=TRANSLATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise _classify_anthropic_error(exc) from exc

        try:
            blocks = response.content
            content = "".join(
                block.text
                for block in blocks
                if getattr(block, "type", None) == "text"
                and isinstance(getattr(block, "text", None), str)
            )
        except (AttributeError, TypeError) as exc:
            raise MalformedTranslationResponse() from exc

        if not content.strip():
            raise MalformedTranslationResponse(
                "Anthropic returned an empty response."
            )

        return parse_translation_payload(content, len(texts))


def _classify_anthropic_error(exc: Exception) -> TranslationError:
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
            "The Anthropic request timed out. Please try again."
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
            "Anthropic rejected the API key. Check ANTHROPIC_API_KEY on the server."
        )
    if (
        status_code == 404
        or name == "NotFoundError"
        or ("model" in message and "not found" in message)
    ):
        return ProviderConfigurationError(
            "The configured Anthropic model is not available. "
            "Check ANTHROPIC_MODEL."
        )
    if (
        (isinstance(status_code, int) and 500 <= status_code < 600)
        or name in {"InternalServerError", "APIConnectionError"}
        or "connection" in name.lower()
        or "temporarily unavailable" in message
        or "overloaded" in message
    ):
        return TransientTranslationError()
    return TranslationError("Anthropic could not complete the translation request.")
