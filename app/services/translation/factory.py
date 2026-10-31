"""Provider selection from settings, without leaking configuration to clients."""

from __future__ import annotations

from app.config import Settings
from app.errors import ProviderConfigurationError
from app.services.translation.base import TranslationProvider
from app.services.translation.gemini import GeminiTranslationProvider
from app.services.translation.mock import MockTranslationProvider
from app.services.translation.openai_compat import OpenAICompatibleTranslationProvider


class UnavailableProvider(TranslationProvider):
    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    def translate(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        raise ProviderConfigurationError(self.reason)


def build_translation_provider(settings: Settings) -> TranslationProvider:
    provider = settings.ai_provider

    if provider == "mock":
        return MockTranslationProvider()

    if provider == "gemini":
        if not settings.gemini_api_key:
            return UnavailableProvider(
                "gemini",
                "Gemini is selected but GEMINI_API_KEY is not set. "
                "Add a free key to .env or set AI_PROVIDER=mock.",
            )
        return GeminiTranslationProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
        )

    if provider in {"openai", "openai_compatible", "groq", "openrouter", "ollama"}:
        if not settings.openai_compat_base_url or not settings.openai_compat_model:
            return UnavailableProvider(
                provider,
                "The OpenAI-compatible provider needs OPENAI_COMPAT_BASE_URL "
                "and OPENAI_COMPAT_MODEL.",
            )
        return OpenAICompatibleTranslationProvider(
            base_url=settings.openai_compat_base_url,
            model=settings.openai_compat_model,
            api_key=settings.openai_compat_api_key,
            timeout_seconds=settings.ai_timeout_seconds,
        )

    return UnavailableProvider(
        provider,
        f"Unknown AI_PROVIDER '{provider}'. Use gemini, openai_compatible or mock.",
    )
