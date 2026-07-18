"""Answer localisation: the aggregator gets a language directive; routing stays English."""
from nextoken_copilot.agents.graph import _language_directive, _LANGUAGES


def test_known_locales_map_to_language_names():
    assert _language_directive("zh-Hant")[0] == "Traditional Chinese"
    assert _language_directive("zh-CN")[0] == "Simplified Chinese"
    assert _language_directive("ar")[0] == "Modern Standard Arabic"
    assert _language_directive("hi")[0] == "Hindi"
    assert _language_directive("es")[0] == "Spanish"


def test_case_insensitive_and_directive_names_the_language():
    name, directive = _language_directive("FR")
    assert name == "French" and "French" in directive


def test_unknown_or_missing_falls_back_to_mirror_user_language():
    for val in (None, "", "xx"):
        name, directive = _language_directive(val)
        assert name == "auto" and "same language" in directive.lower()


def test_all_requested_languages_supported():
    for loc in ["en", "zh-Hans", "zh-Hant", "de", "fr", "es", "ar", "hi"]:
        assert _language_directive(loc)[0] != "auto"
