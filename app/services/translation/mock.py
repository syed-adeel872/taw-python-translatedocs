"""Deterministic mock provider for development and tests."""

from __future__ import annotations

import re

from app.services.translation.base import TranslationProvider

_MARKER_OPEN = re.compile(r"(\[\[\[R\d+\]\]\])")


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
        results: list[str] = []
        for text in texts:
            if "[[[R" in text:
                results.append(
                    _MARKER_OPEN.sub(
                        rf"\1[{target_language}] ", text, count=1
                    )
                )
            else:
                results.append(f"[{target_language}] {text}")
        return results
