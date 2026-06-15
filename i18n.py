"""Lightweight i18n: load json/locales/<lang>.json at startup, look up strings via t(key, **kwargs).

The active language is set once per process via set_language(code). All lookups
go through t(), which interpolates {vars} with str.format. If a key is missing
in the active language but present in English, English is returned. If it's
missing in both, KeyError is raised — that signals a missing translation, not
a silent fallback to a placeholder.

Adding a new language is two steps:
1. Drop json/locales/<code>.json with the same keys as en.json.
2. Add the code to AVAILABLE_LANGUAGES below.
"""

import json
from pathlib import Path

_LOCALES_DIR = Path(__file__).parent / "json" / "locales"
AVAILABLE_LANGUAGES = ("en", "de")
_FALLBACK = "en"

_LOCALES: dict[str, dict] = {}
_ACTIVE: str = _FALLBACK


def _load(code: str) -> dict:
    path = _LOCALES_DIR / f"{code}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_all() -> None:
    for code in AVAILABLE_LANGUAGES:
        _LOCALES[code] = _load(code)


def get_language() -> str:
    return _ACTIVE


def set_language(code: str) -> None:
    """Activate a language. Raises ValueError if the code isn't registered."""
    global _ACTIVE
    if code not in AVAILABLE_LANGUAGES:
        raise ValueError(
            f"Unsupported language: {code!r}. "
            f"Available: {', '.join(AVAILABLE_LANGUAGES)}"
        )
    _ACTIVE = code


def t(key: str, **kwargs) -> str:
    """Look up a translation key in the active language, falling back to English.

    If the key is missing in BOTH languages, raises KeyError so a missing
    translation is loud, not silent. {var} placeholders are filled from kwargs.
    """
    template = _LOCALES.get(_ACTIVE, {}).get(key) or _LOCALES[_FALLBACK].get(key)
    if template is None:
        raise KeyError(f"Translation key {key!r} not in {_FALLBACK!r} or {_ACTIVE!r}")
    return template.format(**kwargs) if kwargs else template


_load_all()
