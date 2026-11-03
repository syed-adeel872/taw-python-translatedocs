"""Google Gemini provider using the free-tier google-genai SDK."""

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
from app.services.translation.prompts import build_batch_prompt


class GeminiTranslationProvider(TranslationProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        if not api_key:
            raise ProviderConfigurationError(
                "Gemini is selected but GEMINI_API_KEY is not set."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ProviderConfigurationError(
                "The Google GenAI SDK is not installed. Install requirements.txt."
            ) from exc

        self._genai = genai
        self._types = types
        self.model = model or "gemini-3.6-flash"

        try:
            http_options = types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retryOptions=types.HttpRetryOptions(attempts=1),
            )
        except Exception:
            http_options = types.HttpOptions(timeout=int(timeout_seconds * 1000))

        try:
            self._client = genai.Client(api_key=api_key, http_options=http_options)
        except Exception:
            self._client = genai.Client(api_key=api_key)

    def translate(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        prompt = build_batch_prompt(texts, source_language, target_language)

        try:
            config = self._types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        except Exception:
            config = None

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            raise _classify_gemini_error(exc) from exc

        raw_text = getattr(response, "text", None)
        if not raw_text:
            raise MalformedTranslationResponse(
                "Gemini returned an empty response. The request may have been blocked "
                "by a safety filter or the model may be unavailable."
            )

        return parse_translation_payload(raw_text, len(texts))


def _classify_gemini_error(exc: Exception) -> TranslationError:
    message = str(exc).lower()
    code = getattr(exc, "code", None)

    if code == 429 or "429" in message or "resource_exhausted" in message or "quota" in message:
        return RateLimitError()
    if code in (401, 403) or "api key" in message or "unauthenticated" in message:
        return ProviderConfigurationError(
            "Gemini rejected the API key. Check GEMINI_API_KEY on the server."
        )
    if code == 404 or "not found" in message:
        return ProviderConfigurationError(
            "The configured Gemini model is not available. Check GEMINI_MODEL."
        )
    if (
        code in (500, 502, 503, 504)
        or "timeout" in message
        or "timed out" in message
        or "deadline" in message
        or "temporarily unavailable" in message
        or "overloaded" in message
    ):
        return TransientTranslationError()
    return TranslationError("Gemini could not complete the translation request.")
