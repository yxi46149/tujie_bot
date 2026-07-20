from __future__ import annotations

from typing import Literal


Language = Literal["zh", "en"]

DEFAULT_LANGUAGE: Language = "zh"
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("zh", "en")


def normalize_language(value: object | None) -> Language:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"en", "english"}:
        return "en"
    if normalized in {"zh", "zh-cn", "cn", "chinese", "中文", "简体中文"}:
        return "zh"
    return DEFAULT_LANGUAGE


def is_english(language: object | None) -> bool:
    return normalize_language(language) == "en"


def pick(language: object | None, zh: str, en: str) -> str:
    return en if is_english(language) else zh
