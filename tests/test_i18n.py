import json
import re
from pathlib import Path

import pytest
import i18n
from i18n import t, set_language, get_language, AVAILABLE_LANGUAGES


def test_default_language_is_english():
    assert get_language() == "en"


def test_set_language_changes_active_locale():
    set_language("de")
    assert get_language() == "de"
    set_language("en")  # cleanup so other tests aren't polluted
    assert get_language() == "en"


def test_unknown_language_raises():
    with pytest.raises(ValueError, match="Unsupported language"):
        set_language("klingon")


def test_t_returns_english_string():
    set_language("en")
    assert t("embed.field.price") == "Price"


def test_t_returns_german_string():
    set_language("de")
    assert t("embed.field.price") == "Preis"
    set_language("en")


def test_t_interpolates_variables():
    set_language("en")
    assert t("command.clear.reply.deleted", n=42) == "42 messages deleted."
    set_language("de")
    assert t("command.clear.reply.deleted", n=42) == "42 Nachrichten gelöscht."
    set_language("en")


def test_t_falls_back_to_english_for_missing_key():
    """If a key is missing in the active language but present in English, return English."""
    # Simulate by monkeypatching the active locale to a dict missing one key.
    original = i18n._LOCALES["de"].copy()
    i18n._LOCALES["de"] = {k: v for k, v in original.items() if k != "embed.field.price"}
    set_language("de")
    assert t("embed.field.price") == "Price"  # fell back to English
    i18n._LOCALES["de"] = original
    set_language("en")


def test_t_raises_keyerror_for_missing_in_both():
    set_language("de")  # regex below requires _ACTIVE == "de"
    with pytest.raises(KeyError, match="not in 'en' or 'de'"):
        t("this.key.does.not.exist")
    set_language("en")  # cleanup


def test_available_languages_lists_en_and_de():
    assert "en" in AVAILABLE_LANGUAGES
    assert "de" in AVAILABLE_LANGUAGES


# ---------------------------------------------------------------------------
# Locale-file hygiene: keys must be referenced in code and present in BOTH
# languages. Catches dead keys at PR time instead of letting them rot.
# ---------------------------------------------------------------------------

def _referenced_keys() -> set[str]:
    """All t() keys that appear in any *.py file under the repo root.

    Static analysis: catches t(\"key\") literals and the first literal in
    t(\"a\" if x else \"b\") expressions. Dynamic lookups built from
    variables cannot be detected; those are accepted as documented gaps
    and are individually audited.
    """
    keys: set[str] = set()
    for py in Path(__file__).resolve().parent.parent.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        for m in re.finditer(r't\(\s*["\']([^"\']+)["\']', py.read_text(encoding="utf-8")):
            keys.add(m.group(1))
    return keys


def _locale_keys(code: str) -> set[str]:
    path = Path(__file__).resolve().parent.parent / "locales" / f"{code}.json"
    return set(json.load(path.open(encoding="utf-8")).keys())


def test_every_locale_key_is_referenced_in_code():
    """A key defined in any locale must be looked up via t() somewhere.

    Dead keys silently rot in the JSON, then quietly appear in the locale
    count in the README badge, then lie to readers about what the bot
    supports. This test fails the moment someone adds a key they
    forget to wire up - and the message names the key.
    """
    used = _referenced_keys()
    # Dynamic lookups that the regex can't see; safe to whitelist.
    documented_gaps = {"embed.field.avg_price.above"}  # notifier.py:42 conditional
    for code in AVAILABLE_LANGUAGES:
        defined = _locale_keys(code)
        dead = sorted(defined - used - documented_gaps)
        assert not dead, (
            f"Dead i18n keys in {code}.json (never used by t()): {dead}"
        )


def test_all_locales_have_identical_key_sets():
    """en.json and de.json must agree on the key set.

    The bot's i18n layer falls back to English for any key missing in the
    active language, so a missing-in-de key would silently degrade for
    German users. Catch drift at PR time.
    """
    keys = {code: _locale_keys(code) for code in AVAILABLE_LANGUAGES}
    reference = keys["en"]
    for code, ks in keys.items():
        missing = reference - ks
        extra = ks - reference
        assert not missing, f"keys in en.json but missing from {code}.json: {sorted(missing)}"
        assert not extra, f"keys in {code}.json but missing from en.json: {sorted(extra)}"
