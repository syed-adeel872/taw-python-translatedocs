"""Supported languages and language helpers."""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "auto": "Auto-detect",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ro": "Romanian",
    "ru": "Russian",
    "uk": "Ukrainian",
    "tr": "Turkish",
    "ar": "Arabic",
    "ur": "Urdu",
    "fa": "Persian",
    "he": "Hebrew",
    "hi": "Hindi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
    "ms": "Malay",
    "sw": "Swahili",
}

RTL_LANGUAGES = {"ar", "ur", "fa", "he"}

TARGET_LANGUAGES: dict[str, str] = {
    code: name for code, name in LANGUAGES.items() if code != "auto"
}


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code or "the source language")


def is_valid_target(code: str) -> bool:
    return code in TARGET_LANGUAGES


def is_valid_source(code: str) -> bool:
    return code in LANGUAGES
