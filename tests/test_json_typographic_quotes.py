import json

import pytest

from raganything.modalprocessors import BaseModalProcessor


@pytest.mark.parametrize("fenced", [False, True])
def test_typographic_json_delimiters_preserve_fields(fenced):
    processor = BaseModalProcessor.__new__(BaseModalProcessor)
    expected = {
        "detailed_description": "An equation",
        "entity_info": {
            "entity_name": "x",
            "entity_type": "equation",
            "summary": "A user's equation",
        },
    }
    response = (
        "{“detailed_description”: “An equation”, "
        "“entity_info”: {“entity_name”: “x”, “entity_type”: “equation”, "
        "“summary”: “A user's equation”}}"
    )
    if fenced:
        response = f"```json\n{response}\n```"

    assert processor._robust_json_parse(response) == expected


def test_cleanup_preserves_typographic_quotes_in_ascii_quoted_strings():
    processor = BaseModalProcessor.__new__(BaseModalProcessor)
    description = 'Keep “quoted” text, a "quote" and the user’s apostrophe'
    response = (
        "{“detailed_description”: " + json.dumps(description, ensure_ascii=False) + "}"
    )

    assert processor._robust_json_parse(response) == {
        "detailed_description": description
    }


def test_valid_json_preserves_typographic_punctuation():
    processor = BaseModalProcessor.__new__(BaseModalProcessor)
    expected = {"detailed_description": "The user\u2019s \u201cquoted\u201d text"}

    assert (
        processor._robust_json_parse(json.dumps(expected, ensure_ascii=False))
        == expected
    )
