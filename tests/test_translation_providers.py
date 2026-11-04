from __future__ import annotations

import pytest

from app.config import Settings
from app.errors import (
    MalformedTranslationResponse,
    ProviderConfigurationError,
    RateLimitError,
)
from app.services.translation import openai_compat
from app.services.translation.base import TranslationProvider, TranslationService
from app.services.translation.factory import UnavailableProvider, build_translation_provider
from app.services.translation.gemini import _classify_gemini_error
from app.services.translation.mock import MockTranslationProvider
from app.services.translation.parsing import parse_translation_payload
from app.services.translation.prompts import build_batch_prompt


def test_mock_provider_marks_text_with_target_language():
    provider = MockTranslationProvider()
    assert provider.translate(["Hello"], "en", "de") == ["[de] Hello"]


def test_parse_fenced_json_list():
    raw = '```json\n["uno", "dos"]\n```'
    assert parse_translation_payload(raw, 2) == ["uno", "dos"]


def test_parse_json_object_with_translations_key():
    raw = '{"translations": ["un", "deux"]}'
    assert parse_translation_payload(raw, 2) == ["un", "deux"]


def test_parse_json_with_surrounding_text():
    raw = 'Here you go: {"translations": ["eins"]} end'
    assert parse_translation_payload(raw, 1) == ["eins"]


def test_parse_accepts_object_items():
    raw = '{"translations": [{"text": "uno"}, {"text": "dos"}]}'
    assert parse_translation_payload(raw, 2) == ["uno", "dos"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", 1),
        ("not json", 1),
        ('{"translations": ["only one"]}', 2),
        ('{"translations": [1, 2]}', 2),
        ('{"unexpected": []}', 1),
    ],
)
def test_parse_rejects_invalid_payloads(raw, expected):
    with pytest.raises(MalformedTranslationResponse):
        parse_translation_payload(raw, expected)


def test_prompt_contains_conciseness_guidance():
    prompt = build_batch_prompt(["Hello", "World"], "en", "es")
    assert "concise" in prompt
    assert "quantity" in prompt.lower() or "quantities" in prompt.lower()


def test_service_batches_and_preserves_order():
    class RecordingProvider(TranslationProvider):
        name = "recording"

        def __init__(self):
            self.batches = []

        def translate(self, texts, source_language, target_language):
            self.batches.append(list(texts))
            return [f"{text}-{target_language}" for text in texts]

    provider = RecordingProvider()
    service = TranslationService(provider, batch_size=2, max_retries=0)
    result = service.translate_texts(["a", "b", "c", "d", ""], "en", "it")

    assert result == ["a-it", "b-it", "c-it", "d-it", ""]
    assert provider.batches == [["a", "b"], ["c", "d"]]


def test_service_splits_very_long_segments():
    class EchoProvider(TranslationProvider):
        name = "echo"

        def translate(self, texts, source_language, target_language):
            return [f"[{target_language}] {text}" for text in texts]

    long_text = ("This is a sentence. " * 300).strip()
    service = TranslationService(EchoProvider(), batch_size=5)
    result = service.translate_texts([long_text], "en", "es")

    assert result[0].count("[es]") >= 2
    assert result[0].startswith("[es] This is a sentence.")


def test_gemini_error_classification():
    class FakeError(Exception):
        def __init__(self, message, code=None):
            super().__init__(message)
            self.code = code

    assert isinstance(_classify_gemini_error(FakeError("resource exhausted", 429)), RateLimitError)
    assert isinstance(
        _classify_gemini_error(FakeError("API key not valid", 400)),
        ProviderConfigurationError,
    )
    assert isinstance(
        _classify_gemini_error(FakeError("permission denied", 403)),
        ProviderConfigurationError,
    )
    assert isinstance(
        _classify_gemini_error(FakeError("model not found", 404)),
        ProviderConfigurationError,
    )
    assert "timeout" not in _classify_gemini_error(FakeError("deadline exceeded")).user_message.lower()
    assert _classify_gemini_error(FakeError("unknown")).__class__.__name__ == "TranslationError"


def test_factory_returns_mock_provider():
    settings = Settings(_env_file=None, ai_provider="mock")
    provider = build_translation_provider(settings)
    assert provider.name == "mock"


def test_factory_reports_missing_gemini_key():
    settings = Settings(_env_file=None, ai_provider="gemini", gemini_api_key="")
    provider = build_translation_provider(settings)
    assert isinstance(provider, UnavailableProvider)
    with pytest.raises(ProviderConfigurationError):
        provider.translate(["hello"], "en", "es")


def test_factory_reports_missing_openai_configuration():
    settings = Settings(_env_file=None, ai_provider="openai_compatible")
    provider = build_translation_provider(settings)
    assert isinstance(provider, UnavailableProvider)


def test_factory_reports_unknown_provider():
    settings = Settings(_env_file=None, ai_provider="made-up")
    provider = build_translation_provider(settings)
    assert isinstance(provider, UnavailableProvider)


def _settings_for_openai() -> Settings:
    return Settings(
        _env_file=None,
        ai_provider="openai_compatible",
        openai_compat_base_url="https://example.invalid/v1",
        openai_compat_model="test-model",
        openai_compat_api_key="test-key",
    )


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_openai_compatible_success(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            return _FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"translations": ["[es] one", "[es] two"]}'
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr(openai_compat.httpx, "Client", FakeClient)
    provider = openai_compat.OpenAICompatibleTranslationProvider(
        base_url="https://example.invalid/v1",
        model="test-model",
        api_key="test-key",
    )
    assert provider.translate(["one", "two"], "en", "es") == ["[es] one", "[es] two"]


def test_openai_compatible_rate_limit(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            return _FakeResponse(429, {})

    monkeypatch.setattr(openai_compat.httpx, "Client", FakeClient)
    provider = openai_compat.OpenAICompatibleTranslationProvider(
        base_url="https://example.invalid/v1", model="test-model"
    )
    with pytest.raises(RateLimitError):
        provider.translate(["one"], "en", "es")


def test_openai_compatible_auth_error(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            return _FakeResponse(401, {})

    monkeypatch.setattr(openai_compat.httpx, "Client", FakeClient)
    provider = openai_compat.OpenAICompatibleTranslationProvider(
        base_url="https://example.invalid/v1", model="test-model"
    )
    with pytest.raises(ProviderConfigurationError):
        provider.translate(["one"], "en", "es")
