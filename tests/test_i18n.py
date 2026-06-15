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
