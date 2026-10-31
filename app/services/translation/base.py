"""Provider interface and retry/batching translation service."""

from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod

from app.errors import (
    MalformedTranslationResponse,
    RateLimitError,
    TransientTranslationError,
    TranslationError,
)

logger = logging.getLogger(__name__)

_SENTENCE_BREAK = re.compile(r"(?<=[.!?。！？])\s+")
MAX_SEGMENT_CHARS = 4_000


class TranslationProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def translate(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        """Return one translated string per input string, in the same order."""


class TranslationService:
    """Adds batching, bounded retries and response validation to a provider."""

    def __init__(
        self,
        provider: TranslationProvider,
        *,
        batch_size: int = 20,
        max_retries: int = 2,
        retry_backoff: float = 0.75,
        max_document_chars: int = 400_000,
    ) -> None:
        self.provider = provider
        self.batch_size = max(1, batch_size)
        self.max_retries = max(0, max_retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.max_document_chars = max_document_chars

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def translate_texts(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        if not texts:
            return []

        total_chars = sum(len(text) for text in texts)
        if total_chars > self.max_document_chars:
            raise TranslationError(
                "This document is too large to translate. "
                f"The limit is {self.max_document_chars:,} characters."
            )

        expanded: list[str] = []
        owners: list[int] = []
        for index, text in enumerate(texts):
            if not text or not text.strip():
                continue
            for part in _split_long_text(text):
                expanded.append(part)
                owners.append(index)

        if not expanded:
            return ["" for _ in texts]

        translated_parts: list[str] = []
        for start in range(0, len(expanded), self.batch_size):
            batch = expanded[start : start + self.batch_size]
            translated_parts.extend(
                self._translate_batch(batch, source_language, target_language)
            )

        grouped: list[list[str]] = [[] for _ in texts]
        for owner, translated in zip(owners, translated_parts):
            grouped[owner].append(translated)

        results: list[str] = []
        for parts in grouped:
            if not parts:
                results.append("")
            elif len(parts) == 1:
                results.append(parts[0])
            else:
                results.append(" ".join(part.strip() for part in parts).strip())
        return results

    def _translate_batch(
        self, batch: list[str], source_language: str, target_language: str
    ) -> list[str]:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                output = self.provider.translate(
                    batch, source_language, target_language
                )
                return self._validate(batch, output)
            except (RateLimitError, TransientTranslationError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                delay = self.retry_backoff * (2**attempt)
                logger.warning(
                    "Translation attempt %s/%s failed (%s); retrying in %.2fs",
                    attempt + 1,
                    self.max_retries + 1,
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)

        raise last_error or TranslationError()

    @staticmethod
    def _validate(inputs: list[str], output: list[str] | None) -> list[str]:
        if not isinstance(output, list) or len(output) != len(inputs):
            raise MalformedTranslationResponse()
        cleaned: list[str] = []
        for source, translated in zip(inputs, output):
            if not isinstance(translated, str):
                raise MalformedTranslationResponse()
            if source.strip() and not translated.strip():
                raise MalformedTranslationResponse()
            cleaned.append(translated.strip() if source.strip() else "")
        return cleaned


def _split_long_text(text: str, limit: int = MAX_SEGMENT_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_BREAK.split(text):
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(sentence) <= limit:
            current = sentence
        else:
            for start in range(0, len(sentence), limit):
                piece = sentence[start : start + limit]
                if len(piece) == limit:
                    chunks.append(piece)
                else:
                    current = piece
    if current:
        chunks.append(current)
    return chunks
