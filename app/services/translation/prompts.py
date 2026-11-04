"""Prompt construction for batch translation."""

from __future__ import annotations

from app.languages import language_name

TRANSLATION_SYSTEM_PROMPT = (
    "You are a translation engine. Reply with JSON only. Never add commentary."
)


def build_batch_prompt(
    texts: list[str], source_language: str, target_language: str
) -> str:
    if source_language == "auto":
        source_label = "the automatically detected source language"
    else:
        source_label = language_name(source_language)

    target_label = language_name(target_language)
    numbered = "\n".join(f"[{index + 1}] {text}" for index, text in enumerate(texts))

    return (
        "You are a professional translator working on international export and "
        "trade documents (invoices, packing lists, contracts, product sheets).\n"
        f"Translate every numbered segment from {source_label} into {target_label}.\n"
        "Rules:\n"
        "- Return exactly one translation for each numbered segment, in the same order.\n"
        "- Do not merge, split, reorder, skip or add segments.\n"
        "- Preserve numbers, currency codes, product codes, addresses, email addresses "
        "and URLs accurately.\n"
    "- Keep the original tone; do not add explanations or commentary.\n"
    "- If a segment contains markers like [[[R0]]]...[[[/R0]]], keep every "
    "marker exactly unchanged, in the same order, and translate only the text "
    "between matching markers.\n"
    "- Keep each translation as concise as the source allows while preserving "
    "every fact, quantity, date, name, price, code, address, and legal meaning. "
    "Do not add words that are not needed for a correct translation.\n"
    "- Do not include the segment numbers in the translations.\n"
        "- Return ONLY valid JSON in this shape: "
        '{"translations": ["first translation", "second translation"]}\n\n'
        f"Segments ({len(texts)} total):\n{numbered}"
    )
