from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.errors import (
    MalformedTranslationResponse,
    ProviderConfigurationError,
    RateLimitError,
    TransientTranslationError,
    TranslationError,
)
from app.services.translation.anthropic_provider import AnthropicTranslationProvider
from app.services.translation.base import TranslationService
from app.services.translation.factory import (
    UnavailableProvider,
    build_translation_provider,
)
from app.services.translation.gemini import GeminiTranslationProvider
from app.services.translation.mock import MockTranslationProvider
from app.services.translation.openai_provider import OpenAITranslationProvider


class FakeProviderError(Exception):
    def __init__(self, message: str = "provider error", status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class APITimeoutError(Exception):
    pass


class FakeGeminiError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def _openai_response(content: str | None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _openai_provider(handler, model: str = "test-model") -> OpenAITranslationProvider:
    provider = OpenAITranslationProvider(api_key="fake-openai-key", model=model)
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=handler))
    )
    return provider


def _anthropic_provider(
    handler, model: str = "test-model"
) -> AnthropicTranslationProvider:
    provider = AnthropicTranslationProvider(
        api_key="fake-anthropic-key", model=model
    )
    provider._client = SimpleNamespace(
        messages=SimpleNamespace(create=handler)
    )
    return provider


def _gemini_provider(handler, model: str = "test-model") -> GeminiTranslationProvider:
    provider = GeminiTranslationProvider(api_key="fake-gemini-key", model=model)
    provider._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=handler)
    )
    return provider


def test_factory_selects_all_supported_providers_without_network_calls():
    cases = [
        (Settings(_env_file=None, ai_provider="mock"), MockTranslationProvider),
        (
            Settings(
                _env_file=None,
                ai_provider="gemini",
                gemini_api_key="fake-gemini-key",
            ),
            GeminiTranslationProvider,
        ),
        (
            Settings(
                _env_file=None,
                ai_provider="openai",
                openai_api_key="fake-openai-key",
            ),
            OpenAITranslationProvider,
        ),
        (
            Settings(
                _env_file=None,
                ai_provider="anthropic",
                anthropic_api_key="fake-anthropic-key",
            ),
            AnthropicTranslationProvider,
        ),
    ]

    for settings, expected_type in cases:
        assert isinstance(build_translation_provider(settings), expected_type)


def test_provider_models_are_configurable_through_settings():
    openai_provider = build_translation_provider(
        Settings(
            _env_file=None,
            ai_provider="openai",
            openai_api_key="fake-openai-key",
            openai_model="custom-openai-model",
        )
    )
    anthropic_provider = build_translation_provider(
        Settings(
            _env_file=None,
            ai_provider="anthropic",
            anthropic_api_key="fake-anthropic-key",
            anthropic_model="custom-anthropic-model",
        )
    )
    gemini_provider = build_translation_provider(
        Settings(
            _env_file=None,
            ai_provider="gemini",
            gemini_api_key="fake-gemini-key",
            gemini_model="custom-gemini-model",
        )
    )

    assert openai_provider.model == "custom-openai-model"
    assert anthropic_provider.model == "custom-anthropic-model"
    assert gemini_provider.model == "custom-gemini-model"


def test_gemini_default_model_is_gemini_3_6_flash():
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        gemini_api_key="fake-gemini-key",
    )
    provider = build_translation_provider(settings)

    assert settings.gemini_model == "gemini-3.6-flash"
    assert provider.model == "gemini-3.6-flash"


def test_missing_openai_key_is_a_configuration_error_not_a_mock_fallback():
    provider = build_translation_provider(
        Settings(_env_file=None, ai_provider="openai", openai_api_key="")
    )

    assert isinstance(provider, UnavailableProvider)
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        provider.translate(["hello"], "en", "es")


def test_missing_anthropic_key_is_a_configuration_error_not_a_mock_fallback():
    provider = build_translation_provider(
        Settings(_env_file=None, ai_provider="anthropic", anthropic_api_key="")
    )

    assert isinstance(provider, UnavailableProvider)
    with pytest.raises(ProviderConfigurationError, match="ANTHROPIC_API_KEY"):
        provider.translate(["hello"], "en", "es")


def test_mock_provider_remains_the_default_and_backward_compatible():
    settings = Settings(_env_file=None, ai_provider="mock")
    provider = build_translation_provider(settings)

    assert settings.ai_provider == "mock"
    assert provider.name == "mock"
    assert provider.translate(["Hello"], "en", "de") == ["[de] Hello"]


def test_openai_translates_in_segment_order():
    def handler(**kwargs):
        assert kwargs["model"] == "test-model"
        assert kwargs["messages"][1]["content"].count("[1]") == 1
        return _openai_response('{"translations": ["uno", "dos", "tres"]}')

    provider = _openai_provider(handler)
    assert provider.translate(["one", "two", "three"], "en", "es") == [
        "uno",
        "dos",
        "tres",
    ]


def test_anthropic_translates_in_segment_order():
    def handler(**kwargs):
        assert kwargs["model"] == "test-model"
        assert kwargs["messages"][0]["role"] == "user"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"translations": ["un", "deux"]}')]
        )

    provider = _anthropic_provider(handler)
    assert provider.translate(["one", "two"], "en", "fr") == ["un", "deux"]


def test_openai_compatible_provider_reports_selected_alias():
    settings = Settings(
        _env_file=None,
        ai_provider="groq",
        openai_compat_base_url="https://api.groq.com/openai/v1",
        openai_compat_model="llama-3.1-8b-instant",
    )
    provider = build_translation_provider(settings)
    assert provider.name == "groq"


def test_gemini_translates_in_segment_order():
    def handler(**kwargs):
        assert kwargs["model"] == "test-model"
        return SimpleNamespace(text='{"translations": ["eins", "zwei"]}')

    provider = _gemini_provider(handler)
    assert provider.translate(["one", "two"], "en", "de") == ["eins", "zwei"]


def test_gemini_requests_json_without_deprecated_sampling_parameters():
    def handler(**kwargs):
        config = kwargs["config"]
        assert config.response_mime_type == "application/json"
        assert config.temperature is None
        assert config.top_p is None
        assert config.top_k is None
        return SimpleNamespace(text='{"translations": ["eins"]}')

    provider = _gemini_provider(handler)
    assert provider.translate(["one"], "en", "de") == ["eins"]


def test_gemini_fallback_config_preserves_system_prompt():
    calls = {"count": 0}

    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.response_mime_type = kwargs.get("response_mime_type")
            self.system_instruction = kwargs.get("system_instruction")
            self.temperature = None
            self.top_p = None
            self.top_k = None

    def fake_generate_content_config(**kwargs):
        calls["count"] += 1
        if "system_instruction" in kwargs:
            raise TypeError("unsupported")
        config = FakeConfig(**kwargs)
        # Simulate the fallback path setting the attribute.
        try:
            setattr(config, "system_instruction", TRANSLATION_SYSTEM_PROMPT)
        except Exception:
            pass
        return config

    provider = _gemini_provider(lambda **kwargs: SimpleNamespace(text='{"translations": ["eins"]}'))
    provider._types.GenerateContentConfig = fake_generate_content_config
    assert provider.translate(["one"], "en", "de") == ["eins"]
    assert calls["count"] == 2
    def handler(**kwargs):
        config = kwargs["config"]
        assert "translation engine" in (config.system_instruction or "").lower()
        return SimpleNamespace(text='{"translations": ["eins"]}')

    provider = _gemini_provider(handler)
    assert provider.translate(["one"], "en", "de") == ["eins"]


def test_gemini_model_not_found_is_safe_and_does_not_reveal_the_key():
    def handler(**kwargs):
        raise FakeGeminiError("model not found", code=404)

    provider = _gemini_provider(handler)

    with pytest.raises(ProviderConfigurationError) as exc_info:
        provider.translate(["one"], "en", "de")
    assert "GEMINI_MODEL" in exc_info.value.user_message
    assert "fake-gemini-key" not in exc_info.value.user_message


@pytest.mark.parametrize("content", [None, "", "not json"])
def test_openai_rejects_empty_or_malformed_responses(content):
    provider = _openai_provider(lambda **kwargs: _openai_response(content))

    with pytest.raises(MalformedTranslationResponse):
        provider.translate(["one"], "en", "es")


@pytest.mark.parametrize("content", [None, "", "not json"])
def test_anthropic_rejects_empty_or_malformed_responses(content):
    def handler(**kwargs):
        if content is None:
            return SimpleNamespace(content=[])
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=content)]
        )

    provider = _anthropic_provider(handler)

    with pytest.raises(MalformedTranslationResponse):
        provider.translate(["one"], "en", "fr")


@pytest.mark.parametrize("text", [None, "", "not json"])
def test_gemini_rejects_empty_or_malformed_responses(text):
    provider = _gemini_provider(lambda **kwargs: SimpleNamespace(text=text))

    with pytest.raises(MalformedTranslationResponse):
        provider.translate(["one"], "en", "de")


def test_openai_auth_error_is_safe_and_does_not_reveal_the_key():
    def handler(**kwargs):
        raise FakeProviderError("invalid api key", status_code=401)

    provider = _openai_provider(handler)

    with pytest.raises(ProviderConfigurationError) as exc_info:
        provider.translate(["one"], "en", "es")
    assert "OPENAI_API_KEY" in exc_info.value.user_message
    assert "fake-openai-key" not in exc_info.value.user_message


def test_anthropic_auth_error_is_safe_and_does_not_reveal_the_key():
    def handler(**kwargs):
        raise FakeProviderError("invalid x-api-key", status_code=401)

    provider = _anthropic_provider(handler)

    with pytest.raises(ProviderConfigurationError) as exc_info:
        provider.translate(["one"], "en", "fr")
    assert "ANTHROPIC_API_KEY" in exc_info.value.user_message
    assert "fake-anthropic-key" not in exc_info.value.user_message


def test_gemini_auth_error_maps_to_configuration_error():
    def handler(**kwargs):
        raise FakeGeminiError("API key not valid", code=400)

    provider = _gemini_provider(handler)

    with pytest.raises(ProviderConfigurationError):
        provider.translate(["one"], "en", "de")


@pytest.mark.parametrize(
    "provider_factory,error",
    [
        (_openai_provider, lambda: FakeProviderError("rate limit", 429)),
        (_anthropic_provider, lambda: FakeProviderError("rate limit", 429)),
        (_gemini_provider, lambda: FakeGeminiError("resource exhausted", 429)),
    ],
)
def test_rate_limit_responses_map_to_rate_limit_error(provider_factory, error):
    def handler(**kwargs):
        raise error()

    provider = provider_factory(handler)

    with pytest.raises(RateLimitError):
        provider.translate(["one"], "en", "es")


@pytest.mark.parametrize(
    "provider_factory,error",
    [
        (_openai_provider, lambda: APITimeoutError("timed out")),
        (_anthropic_provider, lambda: APITimeoutError("timed out")),
        (_gemini_provider, lambda: FakeGeminiError("deadline exceeded")),
    ],
)
def test_timeout_responses_map_to_transient_error(provider_factory, error):
    def handler(**kwargs):
        raise error()

    provider = provider_factory(handler)

    with pytest.raises(TransientTranslationError):
        provider.translate(["one"], "en", "es")


@pytest.mark.parametrize("provider_name", ["openai", "anthropic", "gemini"])
def test_real_providers_retry_transient_failures_then_succeed(provider_name):
    calls = {"count": 0}

    def handler(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise APITimeoutError("timed out")
        if provider_name == "openai":
            return _openai_response('{"translations": ["uno"]}')
        if provider_name == "anthropic":
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text", text='{"translations": ["uno"]}'
                    )
                ]
            )
        return SimpleNamespace(text='{"translations": ["uno"]}')

    provider_factory = {
        "openai": _openai_provider,
        "anthropic": _anthropic_provider,
        "gemini": _gemini_provider,
    }[provider_name]
    service = TranslationService(
        provider_factory(handler), max_retries=1, retry_backoff=0
    )

    assert service.translate_texts(["one"], "en", "es") == ["uno"]
    assert calls["count"] == 2


def test_openai_auth_failures_are_not_retried():
    calls = {"count": 0}

    def handler(**kwargs):
        calls["count"] += 1
        raise FakeProviderError("invalid api key", status_code=401)

    service = TranslationService(
        _openai_provider(handler), max_retries=3, retry_backoff=0
    )

    with pytest.raises(ProviderConfigurationError):
        service.translate_texts(["one"], "en", "es")
    assert calls["count"] == 1


def test_openai_retries_are_bounded():
    calls = {"count": 0}

    def handler(**kwargs):
        calls["count"] += 1
        raise APITimeoutError("timed out")

    service = TranslationService(
        _openai_provider(handler), max_retries=1, retry_backoff=0
    )

    with pytest.raises(TransientTranslationError):
        service.translate_texts(["one"], "en", "es")
    assert calls["count"] == 2


def test_non_retryable_provider_errors_propagate_safely():
    def handler(**kwargs):
        raise FakeProviderError("bad request", status_code=400)

    provider = _openai_provider(handler)

    with pytest.raises(TranslationError) as exc_info:
        provider.translate(["one"], "en", "es")
    assert "fake-openai-key" not in exc_info.value.user_message
