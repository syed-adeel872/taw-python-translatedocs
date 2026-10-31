"""Tolerant parsing of model JSON responses."""

from __future__ import annotations

import json
import re

from app.errors import MalformedTranslationResponse

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_KEYS = ("translations", "items", "texts", "data", "results")


def parse_translation_payload(raw: str | None, expected: int) -> list[str]:
    if not raw or not raw.strip():
        raise MalformedTranslationResponse()

    text = _FENCE.sub("", raw.strip()).strip()
    payload = _load_json(text)

    if isinstance(payload, dict):
        for key in _KEYS:
            if key in payload:
                payload = payload[key]
                break
        else:
            raise MalformedTranslationResponse()

    if not isinstance(payload, list) or len(payload) != expected:
        raise MalformedTranslationResponse()

    translations: list[str] = []
    for item in payload:
        if isinstance(item, str):
            translations.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            translations.append(item["text"])
        else:
            raise MalformedTranslationResponse()
    return translations


def _load_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
    if not starts:
        raise MalformedTranslationResponse()

    start = min(starts)
    end = max(text.rfind("]"), text.rfind("}"))
    if end <= start:
        raise MalformedTranslationResponse()

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise MalformedTranslationResponse() from exc
