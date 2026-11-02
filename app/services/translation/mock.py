"""Deterministic mock provider for development and tests."""

from __future__ import annotations

from app.services.translation.base import TranslationProvider


class MockTranslationProvider(TranslationProvider):
    """Marks text with the target language code.

    This provider never calls a network service. It exists so the whole
    upload -> translate -> download flow can be developed and tested without
    an API key. It must not be presented as real AI translation.
    """

    name = "mock"

    def translate(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        return [f"[{target_language}] {text}" for text in texts]
