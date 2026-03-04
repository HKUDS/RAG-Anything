"""Tests for multilingual prompt template system (addresses #85)."""

import pytest

from raganything.prompt import PROMPTS
from raganything.prompt_manager import (
    set_prompt_language,
    get_prompt_language,
    reset_prompts,
    register_prompt_language,
    get_available_languages,
)


@pytest.fixture(autouse=True)
def _reset_language():
    """Ensure prompts are reset to English after each test."""
    yield
    reset_prompts()


class TestSetPromptLanguage:
    def test_switch_to_chinese(self):
        set_prompt_language("zh")
        assert get_prompt_language() == "zh"
        assert "请" in PROMPTS["QUERY_IMAGE_DESCRIPTION"] or "图" in PROMPTS["QUERY_IMAGE_DESCRIPTION"]

    def test_switch_back_to_english(self):
        set_prompt_language("zh")
        set_prompt_language("en")
        assert get_prompt_language() == "en"
        assert "Please" in PROMPTS["QUERY_IMAGE_DESCRIPTION"] or "briefly" in PROMPTS["QUERY_IMAGE_DESCRIPTION"]

    def test_unknown_language_raises(self):
        with pytest.raises(ValueError, match="Unknown prompt language"):
            set_prompt_language("xx")

    def test_case_insensitive(self):
        set_prompt_language("ZH")
        assert get_prompt_language() == "zh"

    def test_chinese_prompts_have_all_keys(self):
        """Chinese templates should cover all English keys."""
        from raganything.prompts_zh import PROMPTS_ZH

        english_keys = set(PROMPTS.keys())
        chinese_keys = set(PROMPTS_ZH.keys())
        missing = english_keys - chinese_keys
        assert not missing, f"Chinese prompts missing keys: {missing}"


class TestResetPrompts:
    def test_reset_restores_english(self):
        original = PROMPTS["IMAGE_ANALYSIS_SYSTEM"]
        set_prompt_language("zh")
        assert PROMPTS["IMAGE_ANALYSIS_SYSTEM"] != original
        reset_prompts()
        assert PROMPTS["IMAGE_ANALYSIS_SYSTEM"] == original
        assert get_prompt_language() == "en"


class TestRegisterLanguage:
    def test_register_custom_language(self):
        custom = {"IMAGE_ANALYSIS_SYSTEM": "Analyse d'image"}
        register_prompt_language("fr", custom)
        set_prompt_language("fr")
        assert PROMPTS["IMAGE_ANALYSIS_SYSTEM"] == "Analyse d'image"
        # Missing keys should fallback to English
        assert "expert" in PROMPTS["TABLE_ANALYSIS_SYSTEM"].lower() or "analyst" in PROMPTS["TABLE_ANALYSIS_SYSTEM"].lower()

    def test_mixed_case_registration(self):
        custom = {"IMAGE_ANALYSIS_SYSTEM": "Analyse d'image"}
        register_prompt_language("FR", custom)
        # Case-insensitive selection should still work
        set_prompt_language("fr")
        assert PROMPTS["IMAGE_ANALYSIS_SYSTEM"] == "Analyse d'image"


class TestGetAvailableLanguages:
    def test_includes_defaults(self):
        langs = get_available_languages()
        assert "en" in langs
        assert "zh" in langs
